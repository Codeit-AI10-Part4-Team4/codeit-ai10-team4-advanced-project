"""페르소나 평가 — LLM 호출·검증·집계까지 한 줄로 잇는다.

바깥에서 부르는 것은 `evaluate()` 하나다 (07 §5.1).

    evaluate(panel, store, brief, copy) -> EvaluationResult

**신뢰 판단의 근거는 모델의 자기보고가 아니라 코드 검증 결과다.** 응답은 두 관문을
지난다 — Pydantic 스키마, 그리고 근거 대조(`evidence`). 한 번 실패하면 그 페르소나만
1회 재시도하고, 또 실패하면 집계에서 뺀다 (07 §8).

**병렬은 스레드로 한다.** `ChatClient.complete_json` 이 동기라 asyncio 를 쓰려면
공용 `app_core/llm.py` 에 async 를 더해야 하는데, API 호출은 IO 바운드라 스레드로
충분하고 스텁 프로필 테스트도 그대로 돌아간다.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Final

from pydantic import ValidationError

from app_core.llm import ChatClient, get_client
from app_core.panel.aggregate import DEFAULT_SIGMA_MAX, aggregate
from app_core.panel.contrast import contrast
from app_core.panel.evidence import evidence_failures
from app_core.panel.narrator import MOTIVE_KO, PRICE_KO, TIME_KO
from app_core.panel.schemas import (
    ContrastNote,
    EvaluationResult,
    Panel,
    Persona,
    PersonaEval,
    TradeAreaFeatures,
)
from app_core.schema import AdBrief, CopyCandidate, Store

logger = logging.getLogger(__name__)

#: 시안당 평가 콜 상한 (07 R4). 페르소나가 더 많으면 가중치 순으로 자른다.
MAX_EVAL_CALLS = 20

#: 병렬 실행 폭. 콜 상한과 같이 두면 한 번에 다 나간다.
MAX_WORKERS = 8

#: 실패한 페르소나만 다시 부른다. 07 §8 은 1회 재시도로 못박았다.
RETRY_ONCE = 1

#: 평가 전체 마감(초). 07 R4 의 30초 예산에서 대조·요약·집계 몫을 남긴 값이다.
#: 마감을 넘긴 페르소나는 실패로 세고, 신뢰도 사유에 남긴다 — 부분 패널의
#: 점수를 온전한 패널인 척 보여주지 않기 위해서다.
DEFAULT_DEADLINE_S: Final = 25.0

#: LLM 응답에서 서버가 채우는 키. 모델이 이 키를 에코해도(따라 적어도)
#: 오류로 만들지 않는다 — 서버 값이 이긴다. 에코는 흔한 행동이라 이걸 안
#: 벗기면 멀쩡한 평가가 TypeError 로 죽고 재시도(유료)가 낭비된다.
_SERVER_SIDE_KEYS: Final = frozenset({"persona_id"})

#: 사장님 화면에 들어가는 자유 텍스트의 절단 상한. 폭주 출력을 좋은 답이
#: 길다는 이유로 재시도(유료)하느니 자르는 쪽(무료)이 낫다.
_TEXT_CAPS: Final = {"comment": 300, "resistance_detail": 300}

SYSTEM = """너는 아래 특성의 손님이다. 광고를 보고 솔직하게 평가하라.

**부정적 평가를 주저하지 마라.** 좋게 봐주는 것이 목적이 아니다. 이 평가는
사장님이 광고를 내보내기 전에 고칠 기회를 주기 위한 것이라, 후한 점수는 해가 된다.

**점수는 너 자신의 반응이다.** 일반론이 아니라 "나라면 어떨까"로 매겨라.
  attention  이 광고가 눈에 걸리는가 (0~100)
  message    무엇을 파는지 바로 알겠는가 (0~100)
  intent     가볼 마음이 드는가 (0~100)

**resistance** — 가장 큰 걸림돌을 **딱 하나** 고른다.
  price      가격이 부담되거나 값어치를 모르겠다
  message    무슨 말인지 모르겠거나 와닿지 않는다
  relevance  나와 상관없는 광고로 느껴진다
  none       걸리는 게 없다

  **넷 중 하나를 그대로 적는다.** `"price"` 처럼 한 단어만 넣는다.
  두 개 이상을 세로줄이나 쉼표로 잇거나 목록으로 주면 그 응답은 버려진다.

  ※ 광고 이미지는 보지 않았다. **visual 은 고르지 마라.**

**evidence** — 왜 그렇게 느꼈는지를 아래 "우리 동네 숫자"에서 골라 인용한다.
  path 와 value 를 **그대로** 옮겨 적어라. 새 수치를 만들어내면 그 응답은 버려진다.
  최소 1개. 목록에 없는 path 는 쓸 수 없다.

**comment** — 사장님이 읽을 한 문장. 전문용어·분석 용어를 쓰지 마라.
  나쁜 예: "매출 비중 대비 방문 의향이 낮음"
  좋은 예: "9,500원이면 옆집이랑 고민할 것 같아요. '10분 컷'이라는 말엔 끌리네요."

아래 JSON 형식으로만 답해라.

{"attention": 62, "message": 74, "intent": 45,
 "resistance": "price",
 "resistance_detail": "9,500원이면 한 번 더 생각하게 된다",
 "comment": "맛은 궁금한데 가격에서 손이 멈추네요.",
 "evidence": [{"path": "age_share.30", "value": 0.382}]}

**이 예시의 형식만 따르고 값은 베끼지 마라.** 점수·문장·근거는 네 판단으로 채운다."""


def _retry_hint(reason: str) -> str:
    """재시도 프롬프트에 붙일 교정 지시.

    `temperature=0` 이라 같은 입력을 다시 보내면 **같은 오답**이 나온다.
    재시도가 의미를 가지려면 입력이 달라져야 하므로, 무엇을 어겼는지 알려준다.
    무작위성을 올리는 것보다 낫다 — 틀린 지점을 짚어주는 쪽이 교정 확률이 높고
    점수 재현성도 유지된다.
    """
    return f"\n\n## 직전 응답이 규칙을 어겼다\n{reason}\n설명 없이 JSON 하나만 다시 답하라."


SUMMARY_SYSTEM = """손님들의 평가를 사장님이 바로 쓸 수 있는 **개선 제안**으로 옮긴다.

불평을 나열하지 마라. 사장님이 **문구를 어떻게 고치면 되는지**를 쓴다.
  나쁜 예: "가격이 비싸다는 의견이 많았습니다"
  좋은 예: "가격을 낮추기보다 '런치 세트 8,900원'처럼 묶음가로 제시해보세요"

- **2~3개**만. 많으면 아무것도 안 고친다.
- 광고 문구·가격 표현으로 바꿀 수 있는 것만 쓴다. 메뉴를 바꾸라거나 가게를
  옮기라는 제안은 하지 마라.
- 주어진 평가에 없는 내용을 지어내지 마라.

아래 JSON 형식으로만 답해라.

{"suggestions": ["제안 1", "제안 2"]}"""


def _feature_lines(features: TradeAreaFeatures, persona: Persona) -> str:
    """평가에 쓸 숫자만 골라 준다.

    전부 넘기면 토큰이 낭비되고, 자기와 무관한 수치를 인용해도 근거 대조를
    통과해버린다. 그래서 **이 페르소나 자신의 근거 + 상권 공통 값**만 준다.
    `match_distance_m`·`demo_coverage` 는 인용 금지라 애초에 넣지 않는다.
    """
    lines = [f"- {ref.path} = {ref.value}" for ref in persona.evidence]
    lines += [
        f"- avg_ticket = {features.avg_ticket}",
        f"- avg_ticket_pct = {features.avg_ticket_pct}",
        f"- competitor_cnt = {features.competitor_cnt}",
        f"- weekend_ratio = {features.weekend_ratio}",
    ]
    if features.work_ratio is not None:
        lines.append(f"- work_ratio = {features.work_ratio}")
    return "\n".join(lines)


def _ad_lines(store: Store, brief: AdBrief, copy: CopyCandidate) -> str:
    parts = [
        f"- 업종: {store.industry_label}",
        f"- 상호: {store.name}",
        f"- 홍보 대상: {brief.product}",
        f"- 헤드라인: {copy.headline}",
    ]
    if copy.sub:
        parts.append(f"- 서브 문구: {copy.sub}")
    if brief.situation:
        parts.append(f"- 알리려는 것: {brief.situation}")
    if brief.tone:
        parts.append(f"- 원하는 느낌: {brief.tone}")
    # 0 원은 "가격 없음"이라는 뜻이다. 없는 가격을 평가하게 하면 안 된다.
    parts.append(f"- 가격: {brief.price:,}원" if brief.show_price else "- 가격: 광고에 없음")
    return "\n".join(parts)


def build_user_prompt(
    persona: Persona,
    features: TradeAreaFeatures,
    store: Store,
    brief: AdBrief,
    copy: CopyCandidate,
) -> str:
    axes = persona.axes
    return (
        f"## 나\n{persona.demo}. {persona.narrative}\n"
        f"{TIME_KO.get(axes.time, axes.time)}에 주로 움직이고, "
        f"{MOTIVE_KO[axes.motive]} 편, {PRICE_KO[axes.price_sens]} 동네에 산다.\n\n"
        f"## 우리 동네 숫자 (evidence 는 여기서만 고른다)\n"
        f"{_feature_lines(features, persona)}\n\n"
        f"## 광고물\n{_ad_lines(store, brief, copy)}"
    )


def _parse(raw: dict[str, Any], persona_id: str) -> PersonaEval | None:
    """스키마 관문. 형식이 깨지면 None — 부른 쪽이 재시도를 판단한다.

    관문을 넘기 전에 두 가지를 정리한다. 서버가 채우는 키(`persona_id`)는
    모델이 에코해도 벗겨내고, 자유 텍스트는 상한에서 자른다. 둘 다 "고칠 수
    있는 위반을 재시도로 보내지 않는다"는 같은 원칙이다 — 재시도는 유료다.
    """
    if not raw:
        return None
    cleaned = {k: v for k, v in raw.items() if k not in _SERVER_SIDE_KEYS}
    for key, cap in _TEXT_CAPS.items():
        value = cleaned.get(key)
        if isinstance(value, str) and len(value) > cap:
            logger.debug("텍스트 절단 %s.%s (%d자)", persona_id, key, len(value))
            cleaned[key] = value[:cap]
    try:
        return PersonaEval(persona_id=persona_id, **cleaned)
    except (ValidationError, TypeError) as exc:
        logger.debug("스키마 실패 %s: %s", persona_id, exc)
        return None


def _evaluate_one(
    client: ChatClient,
    persona: Persona,
    features: TradeAreaFeatures,
    store: Store,
    brief: AdBrief,
    copy: CopyCandidate,
) -> PersonaEval | None:
    """한 명을 평가한다. 두 관문 중 하나라도 실패하면 1회만 다시 부른다."""
    user = build_user_prompt(persona, features, store, brief, copy)
    hint = ""

    for attempt in range(RETRY_ONCE + 1):
        result = _parse(client.complete_json(SYSTEM, user + hint), persona.persona_id)

        if result is None:
            hint = _retry_hint(
                "JSON 형식이나 값이 스키마에 맞지 않았다. resistance 는 "
                "price · message · relevance · none 중 **하나만** 적는다."
            )
            continue

        failures = evidence_failures(features, result.evidence)
        if not failures:
            return result

        logger.debug("근거 대조 실패 %s (시도 %d): %s", persona.persona_id, attempt + 1, failures)
        paths = ", ".join(f.path for f in failures)
        hint = _retry_hint(
            f"근거로 든 수치가 실제 값과 달랐다 ({paths}). "
            "'우리 동네 숫자'에 적힌 값을 **그대로** 옮겨 적어라."
        )
    return None


def _safe_evaluate_one(
    client: ChatClient,
    persona: Persona,
    features: TradeAreaFeatures,
    store: Store,
    brief: AdBrief,
    copy: CopyCandidate,
) -> PersonaEval | None:
    """`_evaluate_one` 의 예외 방벽.

    스레드 안에서 던져진 예외는 `Future.result()` 까지 숨어 있다가 거기서
    다시 터진다 — 잡지 않으면 네트워크 순단 **한 건**이 나머지 11명의 결과까지
    통째로 버린다. 실패는 그 손님 한 명의 제외로 끝나야 한다.
    """
    try:
        return _evaluate_one(client, persona, features, store, brief, copy)
    except Exception:
        logger.exception("평가 호출 실패 %s — 이 손님만 제외", persona.persona_id)
        return None


def _summarize(client: ChatClient, panel: Panel, evals: list[PersonaEval]) -> list[str]:
    """저항 요인과 코멘트를 개선 제안으로 옮긴다 (07 §7.3).

    07 §7 은 패널 모듈의 LLM 콜을 "서사 1콜 + 평가 ≤20콜 둘뿐"으로 적었지만
    `suggestions` 를 만들 콜이 명세에 없다. 12명 코멘트를 그냥 이어 붙이면
    제안이 아니라 불평 목록이 되므로 집계 뒤 1콜을 더 쓴다 (회당 약 $0.0005).
    아인님 합의 전까지 `summarize=False` 로 끌 수 있게 열어뒀다.
    """
    by_id = {p.persona_id: p for p in panel.personas}
    lines = [
        f"- {by_id[e.persona_id].demo}: {e.comment}"
        + (f" (걸림돌: {e.resistance})" if e.resistance != "none" else "")
        for e in evals
        if e.persona_id in by_id
    ]
    if not lines:
        return []

    raw = client.complete_json(SUMMARY_SYSTEM, "## 손님 반응\n" + "\n".join(lines))
    items = raw.get("suggestions") or []
    return [str(s).strip()[:200] for s in items if isinstance(s, str) and s.strip()][:3]


def evaluate(
    panel: Panel,
    store: Store,
    brief: AdBrief,
    copy: CopyCandidate,
    *,
    ad_id: str = "",
    client: ChatClient | None = None,
    summarize: bool = True,
    sigma_max: float = DEFAULT_SIGMA_MAX,
    deadline_s: float = DEFAULT_DEADLINE_S,
) -> EvaluationResult:
    """광고물 1건을 패널에게 평가받는다.

    Args:
        panel: `build_panel()` 산출물. 근거 대조의 기준값이 여기 있다.
        store: `app_core.schema.Store` — 업종·상호. 주소는 패널 구성에서 이미 썼다.
        brief: `app_core.schema.AdBrief` — 상품·가격·상황·톤.
        copy: 사용자가 고른 문구 후보 1건 (07 §5.1 — 3건 전부는 비용 3배).
        ad_id: 평가 대상 식별자. 결과에 그대로 실린다.
        client: 테스트용 주입구. 없으면 `MODEL_PROFILE` 을 따른다.
        summarize: 개선 제안 요약 콜을 쓸지.
        sigma_max: 분산 체크 임계값.
        deadline_s: 전체 마감(초). 넘긴 페르소나는 실패로 세고 사유에 남긴다.

    Raises:
        AggregationError: 두 관문을 통과한 응답이 하나도 없을 때.
    """
    chat = client or get_client()
    features = panel.features
    started = time.perf_counter()

    # 콜 상한을 넘으면 가중치가 큰 순으로 자른다 — 점수 기여가 큰 쪽을 남긴다.
    targets = sorted(panel.personas, key=lambda p: -p.weight)[:MAX_EVAL_CALLS]

    # `with` 를 쓰지 않는 이유: 블록을 나갈 때 실행 중인 스레드를 **기다린다.**
    # 마감을 넘긴 호출을 기다리면 마감이 마감이 아니게 되므로 버리고 나온다.
    # 버려진 호출은 백그라운드에서 끝나며 토큰은 든다 — 마감을 넘겼을 때만.
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures: dict[Future[PersonaEval | None], Persona] = {
            pool.submit(_safe_evaluate_one, chat, p, features, store, brief, copy): p
            for p in targets
        }
        done, pending = wait(futures, timeout=deadline_s)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # _safe_evaluate_one 이 예외를 전부 삼키므로 result() 는 던지지 않는다.
    outcome = {f: f.result() for f in done}
    evals = [r for r in outcome.values() if r is not None]
    failed_ids = [futures[f].persona_id for f, r in outcome.items() if r is None]
    timed_out = [futures[f].persona_id for f in pending]

    extra_reasons: list[str] = []
    if timed_out:
        extra_reasons.append(
            f"응답 시간 초과로 {len(timed_out)}명을 평가하지 못함 ({deadline_s:.0f}초 한도)"
        )

    logger.info(
        "패널 평가 %s: 요청 %d, 통과 %d, 실패 %d, 시간초과 %d",
        ad_id or "(무명)",
        len(targets),
        len(evals),
        len(failed_ids),
        len(timed_out),
    )

    # 대조는 LLM 을 안 쓴다. 평가가 몇 명 살아남았든 항상 같은 문장이 나오므로
    # 실패율과 무관하게 화면에 근거 A등급 재료를 깔아준다.
    notes = [
        ContrastNote(kind=n.kind, text=n.text, evidence=list(n.evidence))
        for n in contrast(features, brief, copy)
    ]

    suggestions: list[str] = []
    if summarize and evals:
        try:
            suggestions = _summarize(chat, panel, evals)
        except Exception:
            # 요약은 부가물이다. 여기서 터졌다고 이미 끝난 평가를 버리면 안 된다.
            logger.exception("제안 요약 실패 %s — 제안 없이 반환", ad_id or "(무명)")

    return aggregate(
        panel,
        evals,
        ad_id=ad_id,
        suggestions=suggestions,
        failed_ids=failed_ids + timed_out,
        contrast_notes=notes,
        extra_reasons=extra_reasons,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        sigma_max=sigma_max,
    )
