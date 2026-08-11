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
import re
import statistics
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Final

from pydantic import ValidationError

from app_core.llm import ChatClient, get_client
from app_core.panel.aggregate import DEFAULT_SIGMA_MAX, aggregate
from app_core.panel.contrast import TIME_WORDS, contrast
from app_core.panel.evidence import evidence_failures
from app_core.panel.narrator import MOTIVE_KO, PRICE_KO, TIME_KO
from app_core.panel.schemas import (
    METRIC_FIELDS,
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
#: 같은 손님을 몇 번 물어볼지. LLM 의 절대 점수는 같은 입력에도 흔들린다
#: (실측, 아인님: 같은 광고 3회에 53.4 / 53.5 / 63.4). 여러 번 물어 **중앙값**을
#: 쓰면 한 번의 튐이 결과를 흔들지 못한다. 표준편차는 대략 √k 로 줄어든다.
#:
#: 전원에게 k=3 을 쓰면 12명 × 3 = 36콜로 상한(20)을 넘는다. 그래서 **가중치가
#: 큰 손님부터** 남는 예산만큼만 반복한다 — 가중 평균을 실제로 움직이는 쪽의
#: 분산을 줄이는 것이 같은 콜로 얻는 이득이 가장 크다.
DEFAULT_CONSISTENCY_K: Final = 3

_TEXT_CAPS: Final = {"comment": 300, "resistance_detail": 300}

SYSTEM = """너는 아래 특성의 손님이다. 광고를 보고 솔직하게 평가하라.

**부정적 평가를 주저하지 마라.** 좋게 봐주는 것이 목적이 아니다. 이 평가는
사장님이 광고를 내보내기 전에 고칠 기회를 주기 위한 것이라, 후한 점수는 해가 된다.

**점수는 너 자신의 반응이다.** 일반론이 아니라 "나라면 어떨까"로 매겨라.
  attention  이 광고가 눈에 걸리는가 (0~100)
  message    무엇을 파는지 바로 알겠는가 (0~100)
  intent     가볼 마음이 드는가 (0~100)

**점수 기준** — 숫자만 주면 사람마다 척도가 달라진다. 아래에 맞춰 매겨라.
   0~20   그냥 지나친다. 눈에 들어오지도 않았다
  21~40   보긴 했는데 마음이 움직이지 않는다
  41~60   괜찮네 정도. 지금 당장은 아니다
  61~80   한번 가볼까 싶다
  81~100  지금 가고 싶다. 저장하거나 남에게 보낸다

  **60점대에 몰아 쓰지 마라.** 안 끌리면 20점대를, 확 끌리면 90점대를 쓴다.

**resistance** — 가장 큰 걸림돌을 **딱 하나** 고른다.
  price      가격이 부담되거나 값어치를 모르겠다
  message    무슨 말인지 모르겠거나 와닿지 않는다
  relevance  나와 상관없는 광고로 느껴진다
  none       걸리는 게 없다

  **넷 중 하나를 그대로 적는다.** `"price"` 처럼 한 단어만 넣는다.
  두 개 이상을 세로줄이나 쉼표로 잇거나 목록으로 주면 그 응답은 버려진다.

  **네가 매긴 방문 의향과 앞뒤가 맞아야 한다.**
  `intent` 를 60 이상으로 줬다면 `none` 을 골라라 — 가겠다고 해놓고 걸림돌을
  대는 것은 말이 안 된다. 걸림돌은 **네가 안 가는 이유**이지 광고의 흠이 아니다.

  **가격이 이 동네 평균과 비슷하면 `price` 가 아니다.** 위 "우리 동네 숫자"의
  `avg_ticket` 과 견줘봐라. 비슷한데 비싸다고 하면 그건 이 동네 얘기가 아니다.

  **네 처지에서 고른다.** 이 동네가 놓치고 있는 층이라면 "나와 상관없다"
  (relevance)가 더 정확할 때가 많다. 억지로 흠을 찾지 마라.

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
  좋은 예: "가격이 걸린다는 반응이 많으니 양이나 소요 시간을 함께 적어보세요"

**금액을 만들어내지 마라.** 아래 "사실"에 적힌 숫자 말고 다른 금액은 한 글자도
쓸 수 없다. "얼마로 낮추세요" 같은 제안도 하지 마라 — 가격은 사장님이 정하는
값이고, 우리는 **가격을 어떻게 보여줄지**만 제안한다.
  쓸 수 없음: "9,500원에서 8,500원으로 낮춰보세요"
  쓸 수 있음: "가격을 낮추기보다 세트 구성으로 묶어 보여주세요"

- **2~3개**만. 많으면 아무것도 안 고친다.
- 광고 문구·표현으로 바꿀 수 있는 것만 쓴다. 메뉴를 바꾸라거나 가게를
  옮기라는 제안은 하지 마라.
- 주어진 평가에 없는 내용을 지어내지 마라.

아래 JSON 형식으로만 답해라.

{"suggestions": ["가격을 낮추기보다 세트 구성으로 묶어 보여주세요"]}"""


#: 제안에서 "9,500원" 같은 금액을 찾는다. 사장님 화면에 실제와 다른 금액이
#: 뜨는 것을 코드로 막기 위한 것이다.
_AMOUNT_RE: Final = re.compile(r"(\d[\d,]*)\s*원")


def _amounts(text: str) -> set[int]:
    out: set[int] = set()
    for raw in _AMOUNT_RE.findall(text):
        try:
            out.add(int(raw.replace(",", "")))
        except ValueError:
            continue
    return out


#: "있는 만큼 사는가" 판정 경계. `narrator` 와 같은 값을 쓴다 — 서사와 평가가
#: 다른 기준으로 같은 손님을 설명하면 모델이 헷갈린다.
_POOL_HIGH: Final = 1.15
_POOL_LOW: Final = 0.85


def standing(features: TradeAreaFeatures, persona: Persona) -> str:
    """이 손님이 동네에서 **핵심 고객인지 놓치는 층인지**.

    12명이 받는 정보 중 실제로 다른 것은 나이·성별과 이 위치뿐이다.
    축(price_sens·motive)은 상권 단위라 전원 같다.

    실측(2026-08-11)에서 손님 편차가 **0.0** 으로 나왔다 — 12명이 한 명도
    빠짐없이 같은 점수를 냈다는 뜻이고, "12명 패널"이 사실상 1명이었다.
    자기가 이 동네에서 어떤 위치인지를 문장으로 주면 갈리는지 본다.

    `age_share / max(유동, 배후지)` 는 "닿을 수 있었는데 샀는가"를 뜻한다.
    """
    age = persona.demo[:2]
    pool = max(
        features.foot_age_share.get(age, 0.0),
        (features.back_age_share or {}).get(age, 0.0),
    )
    share = features.age_share.get(age, 0.0)
    if pool <= 0 or share <= 0:
        return "너는 이 동네 데이터에 거의 잡히지 않는 층이다."
    ratio = share / pool
    if ratio >= _POOL_HIGH:
        return (
            f"너는 이 동네 **핵심 고객**이다 — 지나다니는 비중보다 실제로 사는 "
            f"비중이 {ratio:.1f}배 높다. 이런 가게를 자주 이용하는 편이다."
        )
    if ratio <= _POOL_LOW:
        return (
            f"너는 이 동네가 **놓치고 있는 층**이다 — 지나다니긴 하지만 실제로는 "
            f"그 비중의 {ratio:.1f}배만큼만 산다. 이런 가게에 잘 들르지 않는다."
        )
    return "너는 있는 만큼 사는, 평범한 비중의 손님이다."


def mentioned_slot(copy: CopyCandidate) -> str | None:
    """광고가 말한 시간대. 없으면 None.

    `contrast.TIME_WORDS` 를 그대로 쓴다 — 목록을 복사해두면 한쪽만 늘었을 때
    대조와 평가가 서로 다른 시간대를 보게 된다.
    """
    text = f"{copy.headline} {copy.sub}"
    return next(
        (slot for slot, words in TIME_WORDS.items() if any(w in text for w in words)),
        None,
    )


def offered_paths(
    features: TradeAreaFeatures,
    persona: Persona,
    copy: CopyCandidate | None = None,
) -> frozenset[str]:
    """이 손님에게 실제로 보여준 숫자의 경로.

    프롬프트와 근거 게이트가 **같은 목록**을 봐야 한다. 따로 관리하면 한쪽만
    바뀌었을 때 멀쩡한 근거가 탈락하거나 엉뚱한 근거가 통과한다.

    **광고가 말한 시간대는 따로 넣는다.** 페르소나의 기본 근거에는 자기가
    움직이는 시간대만 들어 있어서, 광고가 다른 때를 말하면 그 수치를 아무도
    못 받는다 — 실측(2026-08-11): "새벽 감성" 광고에 `time_share.00-06`
    (0.0007)을 받은 손님이 0명이라 "이 동네는 새벽에 안 산다"를 숫자로 말할
    방법이 없었고, 시간대 쌍 판별 점수차가 +2.3 에 그쳤다(가격 쌍은 +25.5).
    """
    paths = {ref.path for ref in persona.evidence}
    paths |= {"avg_ticket", "avg_ticket_pct", "competitor_cnt", "weekend_ratio"}
    if features.work_ratio is not None:
        paths.add("work_ratio")
    if copy is not None:
        slot = mentioned_slot(copy)
        if slot is not None and slot in features.time_share:
            paths.add(f"time_share.{slot}")
    return frozenset(paths)


def _feature_lines(
    features: TradeAreaFeatures, persona: Persona, copy: CopyCandidate | None = None
) -> str:
    """평가에 쓸 숫자만 골라 준다.

    전부 넘기면 토큰이 낭비되고, 자기와 무관한 수치를 인용해도 근거 대조를
    통과해버린다. 그래서 **이 페르소나 자신의 근거 + 상권 공통 값**만 준다.
    `match_distance_m`·`demo_coverage` 는 인용 금지라 애초에 넣지 않는다.
    """
    from app_core.panel.evidence import resolve

    lines = []
    for path in sorted(offered_paths(features, persona, copy)):
        resolved = resolve(features, path)
        if resolved is not None:
            value = int(resolved.value) if resolved.exact else round(resolved.value, 4)
            lines.append(f"- {path} = {value}")
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
        f"{MOTIVE_KO[axes.motive]} 편, {PRICE_KO[axes.price_sens]} 동네에 산다.\n"
        f"{standing(features, persona)}\n\n"
        f"## 우리 동네 숫자 (evidence 는 여기서만 고른다)\n"
        f"{_feature_lines(features, persona, copy)}\n\n"
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
    allowed = offered_paths(features, persona, copy)
    hint = ""

    for attempt in range(RETRY_ONCE + 1):
        result = _parse(client.complete_json(SYSTEM, user + hint), persona.persona_id)

        if result is None:
            hint = _retry_hint(
                "JSON 형식이나 값이 스키마에 맞지 않았다. resistance 는 "
                "price · message · relevance · none 중 **하나만** 적는다."
            )
            continue

        # 그 손님에게 보여준 숫자만 근거로 인정한다 — 값이 맞아도 남의 것이면
        # "정확한 인용"일 뿐 자기 판단의 근거가 아니다.
        failures = evidence_failures(features, result.evidence, allowed)
        if not failures:
            return result

        logger.debug("근거 대조 실패 %s (시도 %d): %s", persona.persona_id, attempt + 1, failures)
        paths = ", ".join(f.path for f in failures)
        if any(f.reason == "off_prompt" for f in failures):
            hint = _retry_hint(
                f"'우리 동네 숫자' 에 없는 항목을 근거로 들었다 ({paths}). "
                "**그 목록에 적힌 것만** 인용할 수 있다."
            )
        else:
            hint = _retry_hint(
                f"근거로 든 수치가 실제 값과 달랐다 ({paths}). "
                "'우리 동네 숫자'에 적힌 값을 **그대로** 옮겨 적어라."
            )
    return None


def _merge_samples(samples: list[PersonaEval]) -> PersonaEval:
    """같은 손님의 여러 응답을 하나로 합친다.

    점수는 **중앙값** — 평균이 아니다. 한 번의 극단값(53·53·63 의 63)이
    평균은 끌고 가지만 중앙값은 못 흔든다.

    코멘트·근거는 지어내지 않고 **중앙값에 가장 가까운 응답의 것**을 쓴다.
    합성 문장을 만들면 그 문장은 아무도 하지 않은 말이 된다.
    """
    if len(samples) == 1:
        return samples[0]

    medians = {
        name: round(statistics.median(getattr(s, name) for s in samples)) for name in METRIC_FIELDS
    }
    representative = min(
        samples,
        key=lambda s: sum(abs(getattr(s, n) - medians[n]) for n in METRIC_FIELDS),
    )
    # 저항 요인은 수치가 아니라 라벨이라 중앙값이 없다 — 최빈값을 쓴다.
    resistance = Counter(s.resistance for s in samples).most_common(1)[0][0]
    return representative.model_copy(update={**medians, "resistance": resistance})


def _sample_plan(targets: list[Persona], k: int) -> dict[str, int]:
    """누구를 몇 번 물어볼지. 남는 콜을 가중치 큰 순으로 나눠준다.

    요약 콜 1개를 남겨두고 계산한다.
    """
    if k <= 1:
        return {p.persona_id: 1 for p in targets}
    budget = MAX_EVAL_CALLS - len(targets) - 1
    plan = {p.persona_id: 1 for p in targets}
    for persona in targets:  # 이미 가중치 내림차순
        extra = min(k - 1, budget)
        if extra <= 0:
            break
        plan[persona.persona_id] += extra
        budget -= extra
    return plan


def _safe_evaluate_one(
    client: ChatClient,
    persona: Persona,
    features: TradeAreaFeatures,
    store: Store,
    brief: AdBrief,
    copy: CopyCandidate,
    samples: int = 1,
) -> PersonaEval | None:
    """`_evaluate_one` 의 예외 방벽.

    스레드 안에서 던져진 예외는 `Future.result()` 까지 숨어 있다가 거기서
    다시 터진다 — 잡지 않으면 네트워크 순단 **한 건**이 나머지 11명의 결과까지
    통째로 버린다. 실패는 그 손님 한 명의 제외로 끝나야 한다.
    """
    collected: list[PersonaEval] = []
    for _ in range(max(1, samples)):
        try:
            one = _evaluate_one(client, persona, features, store, brief, copy)
        except Exception:
            logger.exception("평가 호출 실패 %s — 이 표본만 버림", persona.persona_id)
            continue
        if one is not None:
            collected.append(one)
    if not collected:
        return None
    return _merge_samples(collected)


def _summarize(
    client: ChatClient,
    panel: Panel,
    evals: list[PersonaEval],
    brief: AdBrief,
) -> list[str]:
    """저항 요인과 코멘트를 개선 제안으로 옮긴다 (07 §7.3).

    07 §7 은 패널 모듈의 LLM 콜을 "서사 1콜 + 평가 ≤20콜 둘뿐"으로 적었지만
    `suggestions` 를 만들 콜이 명세에 없다. 12명 코멘트를 그냥 이어 붙이면
    제안이 아니라 불평 목록이 되므로 집계 뒤 1콜을 더 쓴다 (회당 약 $0.0005).

    **금액은 두 겹으로 막는다.** 프롬프트에 실제 가격·객단가를 주어 지어낼
    이유를 없애고, 그래도 다른 금액이 나오면 그 제안을 버린다.

    페르소나 응답은 근거 대조를 거치는데 제안만 그냥 통과하면, 검증받지 않은
    숫자가 사장님 화면에 뜬다 — 실측(아인님, 2026-08-11): 광고가 6,000원인데
    "9,500원에서 8,500원으로"가 3회 중 3회 나왔다. 손님 12명은 6,000원을
    정확히 쓰고 있었으니 요약 콜만의 문제였다.

    01 문서의 팀 원칙과도 맞다: "가격은 AI 가 생성하지 않고 사장님이 직접 입력".
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

    features = panel.features
    allowed = {features.avg_ticket}
    facts = [f"- 이 동네 {features.category_nm} 결제 1건 평균: {features.avg_ticket:,}원"]
    if brief.show_price:
        allowed.add(brief.price)
        facts.insert(0, f"- 광고에 적은 가격: {brief.price:,}원")
    else:
        facts.insert(0, "- 광고에 가격이 없다. 가격 얘기를 꺼내지 마라.")

    raw = client.complete_json(
        SUMMARY_SYSTEM,
        "## 사실 (이 숫자만 쓸 수 있다)\n"
        + "\n".join(facts)
        + "\n\n## 손님 반응\n"
        + "\n".join(lines),
    )

    out: list[str] = []
    for item in raw.get("suggestions") or []:
        if not isinstance(item, str) or not item.strip():
            continue
        text = item.strip()[:200]
        invented = _amounts(text) - allowed
        if invented:
            # 버리고 로그로 남긴다. 고쳐 쓰면 문장이 어색해지고, 무엇보다
            # 그 제안의 근거 자체가 없던 숫자다.
            logger.warning("지어낸 금액이 있어 제안을 버림: %s (금액 %s)", text, invented)
            continue
        out.append(text)
    return out[:3]


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
    consistency_k: int = DEFAULT_CONSISTENCY_K,
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
        consistency_k: 같은 손님을 몇 번 물어 중앙값을 쓸지. 남는 콜 예산만큼
            가중치가 큰 손님부터 적용된다. 1 이면 끈다.

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
        plan = _sample_plan(targets, consistency_k)
        futures: dict[Future[PersonaEval | None], Persona] = {
            pool.submit(
                _safe_evaluate_one,
                chat,
                p,
                features,
                store,
                brief,
                copy,
                plan[p.persona_id],
            ): p
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
        "패널 평가 %s: 요청 %d(콜 %d), 통과 %d, 실패 %d, 시간초과 %d",
        ad_id or "(무명)",
        len(targets),
        sum(plan.values()),
        len(evals),
        len(failed_ids),
        len(timed_out),
    )

    # 대조는 LLM 을 안 쓴다. 평가가 몇 명 살아남았든 항상 같은 문장이 나오므로
    # 실패율과 무관하게 화면에 근거 A등급 재료를 깔아준다.
    notes = [
        ContrastNote(kind=n.kind, text=n.text, evidence=list(n.evidence), fit=n.fit)
        for n in contrast(features, brief, copy)
    ]

    suggestions: list[str] = []
    if summarize and evals:
        try:
            suggestions = _summarize(chat, panel, evals, brief)
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
