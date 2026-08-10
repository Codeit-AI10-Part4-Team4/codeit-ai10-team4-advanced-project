"""광고가 **실제로 쓴 말**과 이 동네의 **실측 수치**를 나란히 놓는다.

LLM 이 없다. 순수 함수라 같은 입력이면 항상 같은 출력이고, 모든 문장이
서울시 원본 수치에서 뺄셈·나눗셈으로 나온다 — 근거 등급 A 다.

**판정하지 않는다.** "이 광고는 틀렸습니다"라고 말하지 않고 "광고는 X 라 하고
이 동네는 Y 입니다"까지만 쓴다. 이유가 둘 있다.

1. 광고가 겨냥한 손님을 우리는 모른다. 주문서(`AdBrief`)에 타깃 칸이 없고,
   말투로 짐작하는 것은 독해가 아니라 추측이라 근거로 쓸 수 없다.
2. 안다 해도 "동네 다수와 다르다 = 잘못됐다"가 아니다. 경쟁이 없는 층을
   노린 전략일 수 있는데 데이터는 그 둘을 구분하지 못한다.

그래서 판단은 사장님이 한다. 우리는 숫자만 갖다 놓는다.
"""

from __future__ import annotations

from typing import Final, NamedTuple

from app_core.panel.schemas import FeatureRef, TradeAreaFeatures
from app_core.schema import AdBrief, CopyCandidate

#: 광고 문구에서 시점을 알아채는 말. 짐작이 아니라 **문면**이다 —
#: 이 단어가 문구에 있으면 광고가 그 시간대를 말한 것이 맞다.
TIME_WORDS: Final[dict[str, tuple[str, ...]]] = {
    "06-11": ("아침", "모닝", "브런치", "출근", "조식"),
    "11-14": ("점심", "런치", "정오"),
    "14-17": ("오후", "티타임", "간식"),
    "17-21": ("저녁", "퇴근", "디너", "회식"),
    "21-24": ("야식", "심야", "밤늦", "늦은 밤"),
}
WEEKEND_WORDS: Final = ("주말", "토요일", "일요일", "주말한정", "휴일")
SLOT_KO: Final[dict[str, str]] = {
    "00-06": "새벽",
    "06-11": "아침(6~11시)",
    "11-14": "점심(11~14시)",
    "14-17": "오후(14~17시)",
    "17-21": "저녁(17~21시)",
    "21-24": "밤(21시 이후)",
}


class Note(NamedTuple):
    """대조 한 건. `text` 는 사장님이 그대로 읽는 문장이다."""

    kind: str
    text: str
    evidence: list[FeatureRef]


def _text(copy: CopyCandidate) -> str:
    return f"{copy.headline} {copy.sub}"


def price_note(features: TradeAreaFeatures, brief: AdBrief) -> Note | None:
    """광고에 적은 가격과 이 동네 객단가를 나란히 놓는다.

    ⚠️ 둘은 같은 단위가 아니다. 객단가는 **결제 1건**의 평균이라 여러 개를
    산 경우가 섞여 있고, 광고 가격은 **품목 하나**다. 그래서 "비싸다/싸다"로
    말하지 않고 두 숫자를 그대로 보여준다. 문장에도 그 차이를 적는다.
    """
    if not brief.show_price:
        return None
    pct = round(features.avg_ticket_pct * 100)
    return Note(
        kind="price",
        text=(
            f"광고에 적은 가격은 {brief.price:,}원입니다. "
            f"이 동네 {features.category_nm} 결제 1건의 평균은 {features.avg_ticket:,}원이고, "
            f"서울 같은 업종 중 상위 {100 - pct}% 수준입니다. "
            "(결제 1건에는 여러 개를 산 경우가 섞여 있어 품목 가격과 직접 비교되지는 않습니다)"
        ),
        evidence=[
            FeatureRef(path="avg_ticket", value=float(features.avg_ticket)),
            FeatureRef(path="avg_ticket_pct", value=features.avg_ticket_pct),
        ],
    )


def timing_note(features: TradeAreaFeatures, copy: CopyCandidate) -> Note | None:
    """광고가 말한 시간대의 매출 비중을 알려준다. 시점 언급이 없으면 None."""
    text = _text(copy)
    slot = next((s for s, words in TIME_WORDS.items() if any(w in text for w in words)), None)
    if slot is None or slot not in features.time_share:
        return None
    share = features.time_share[slot]
    top = max(features.time_share, key=lambda k: features.time_share[k])
    line = (
        f"광고가 {SLOT_KO[slot]}를 말합니다. "
        f"이 동네 {features.category_nm} 매출의 {share * 100:.0f}%가 그 시간대에 나옵니다."
    )
    if top != slot:
        line += (
            f" 가장 많이 팔리는 때는 {SLOT_KO[top]}로 {features.time_share[top] * 100:.0f}%입니다."
        )
    return Note(
        kind="timing",
        text=line,
        evidence=[FeatureRef(path=f"time_share.{slot}", value=share)],
    )


def weekend_note(features: TradeAreaFeatures, copy: CopyCandidate) -> Note | None:
    """광고가 주말을 말할 때만 나온다."""
    if not any(w in _text(copy) for w in WEEKEND_WORDS):
        return None
    return Note(
        kind="weekend",
        text=(
            f"광고가 주말을 말합니다. 이 동네 {features.category_nm} 매출의 "
            f"{features.weekend_ratio * 100:.0f}%가 주말에 나옵니다."
        ),
        evidence=[FeatureRef(path="weekend_ratio", value=features.weekend_ratio)],
    )


def composition_note(features: TradeAreaFeatures) -> Note:
    """동네 구성을 사실 그대로. 광고와 대조하지 않는다 — 타깃을 모르기 때문이다."""
    age = max(features.age_share, key=lambda k: features.age_share[k])
    gen = max(features.gender_share, key=lambda k: features.gender_share[k])
    gen_ko = "여성" if gen == "F" else "남성"
    return Note(
        kind="composition",
        text=(
            f"이 동네에서 {features.category_nm}에 돈을 쓰는 사람은 "
            f"{age}대가 {features.age_share[age] * 100:.0f}%로 가장 많고, "
            f"{gen_ko}이 {features.gender_share[gen] * 100:.0f}%입니다. "
            "누구를 겨냥할지는 사장님이 정하시면 됩니다."
        ),
        evidence=[
            FeatureRef(path=f"age_share.{age}", value=features.age_share[age]),
            FeatureRef(path=f"gender_share.{gen}", value=features.gender_share[gen]),
        ],
    )


def contrast(features: TradeAreaFeatures, brief: AdBrief, copy: CopyCandidate) -> list[Note]:
    """대조 전체. 해당 없는 항목은 빠지고, 동네 구성은 항상 들어간다."""
    notes = [
        price_note(features, brief),
        timing_note(features, copy),
        weekend_note(features, copy),
        composition_note(features),
    ]
    return [n for n in notes if n is not None]
