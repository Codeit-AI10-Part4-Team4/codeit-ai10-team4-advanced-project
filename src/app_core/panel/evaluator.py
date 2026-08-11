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
from concurrent.futures import ThreadPoolExecutor
from typing import Any

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
    """스키마 관문. 형식이 깨지면 None — 부른 쪽이 재시도를 판단한다."""
    if not raw:
        return None
    try:
        return PersonaEval(persona_id=persona_id, **raw)
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
    return [str(s).strip() for s in items if isinstance(s, str) and s.strip()][:3]


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

    Raises:
        AggregationError: 두 관문을 통과한 응답이 하나도 없을 때.
    """
    chat = client or get_client()
    features = panel.features

    # 콜 상한을 넘으면 가중치가 큰 순으로 자른다 — 점수 기여가 큰 쪽을 남긴다.
    targets = sorted(panel.personas, key=lambda p: -p.weight)[:MAX_EVAL_CALLS]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(
            pool.map(
                lambda p: _evaluate_one(chat, p, features, store, brief, copy),
                targets,
            )
        )

    evals = [r for r in results if r is not None]
    # 재시도까지 실패해 응답 자체가 없는 페르소나. 집계에 넘겨야 `excluded_cnt` 가
    # 두 관문의 실패를 모두 센다 — 앞단 실패를 빼면 투명성 지표가 거짓이 된다.
    failed_ids = [p.persona_id for p, r in zip(targets, results, strict=True) if r is None]
    logger.info(
        "패널 평가 %s: 요청 %d, 통과 %d, 탈락 %d",
        ad_id or "(무명)",
        len(targets),
        len(evals),
        len(failed_ids),
    )

    # 대조는 LLM 을 안 쓴다. 평가가 몇 명 살아남았든 항상 같은 문장이 나오므로
    # 실패율과 무관하게 화면에 근거 A등급 재료를 깔아준다.
    notes = [
        ContrastNote(kind=n.kind, text=n.text, evidence=list(n.evidence))
        for n in contrast(features, brief, copy)
    ]

    suggestions = _summarize(chat, panel, evals) if summarize and evals else []
    return aggregate(
        panel,
        evals,
        ad_id=ad_id,
        suggestions=suggestions,
        failed_ids=failed_ids,
        contrast_notes=notes,
        sigma_max=sigma_max,
    )
