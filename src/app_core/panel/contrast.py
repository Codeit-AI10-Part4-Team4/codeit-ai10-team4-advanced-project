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

from math import log2
from typing import Final, NamedTuple

from app_core.panel.schemas import FeatureRef, TradeAreaFeatures
from app_core.schema import AdBrief, CopyCandidate

#: 광고 문구에서 시점을 알아채는 말. 짐작이 아니라 **문면**이다 —
#: 이 단어가 문구에 있으면 광고가 그 시간대를 말한 것이 맞다.
TIME_WORDS: Final[dict[str, tuple[str, ...]]] = {
    # 00-06 을 빠뜨렸다가 "새벽 감성 크로플" 광고를 시점 미언급으로 처리했다.
    # `SLOT_KO` 에는 있는데 여기에만 없어서 눈에 안 띄었다.
    "00-06": ("새벽", "동틀", "해 뜨기 전", "첫차"),
    "06-11": ("아침", "모닝", "브런치", "출근", "조식"),
    "11-14": ("점심", "런치", "정오"),
    # "간식" 을 뺐다. 시점이 아니라 **음식 분류**라 아무 때나 먹는다 —
    # A/B 측정에서 "8,900원으로 즐기는 특별한 간식!" 이 오후(14~17시) 광고로
    # 잡혀 적합도 0.40 이 붙었다. 사장님은 시간대를 말한 적이 없다.
    # 다른 끼니말(점심·저녁·야식·브런치·조식)은 그 자체가 때를 가리키므로 남긴다.
    "14-17": ("오후", "티타임"),
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
    """대조 한 건. `text` 는 사장님이 그대로 읽는 문장이다.

    `fit` 은 0~1 의 적합도. **해당 없으면 None** 이고, 그 항목은 점수에서 빠진다
    (광고가 시점을 말하지 않았는데 시점 적합도를 매길 수는 없다).
    """

    kind: str
    text: str
    evidence: list[FeatureRef]
    fit: float | None = None


def _text(copy: CopyCandidate) -> str:
    return f"{copy.headline} {copy.sub}"


def _josa(word: str, with_batchim: str, without: str) -> str:
    """받침에 맞는 조사. 업종명이 데이터에서 오므로 미리 정해둘 수 없다.

    안 하면 "커피-음료은" · "새벽를 말합니다" 처럼 나온다. 사장님이 읽을
    문장이라 그대로 두면 만든 티가 난다.
    """
    ch = word.strip()[-1:] or " "
    if "가" <= ch <= "힣":
        return with_batchim if (ord(ch) - 0xAC00) % 28 else without
    return without  # 한글이 아니면(숫자·괄호 등) 받침 없는 쪽으로 둔다


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
        fit=_price_fit(brief.price, features.avg_ticket),
    )


def _price_fit(price: int, avg_ticket: int) -> float | None:
    """객단가 대비 광고 가격. **싼 쪽은 감점하지 않는다.**

    객단가는 결제 1건(여러 개를 산 경우 포함)의 평균이라, 품목 하나가 그보다
    싼 것은 정상이다. 반대로 객단가를 크게 넘으면 이 동네에서 이례적이다.
    한쪽만 감점하는 이유가 그것이다.

    2배마다 1/3씩 깎는다 — 45,000원(4.7배)이 0.26, 12,000원(1.26배)이 0.89.
    """
    if avg_ticket <= 0 or price <= 0:
        return None
    ratio = price / avg_ticket
    if ratio <= 1.0:
        return 1.0
    return max(0.0, 1.0 - log2(ratio) / 3.0)


def timing_note(features: TradeAreaFeatures, copy: CopyCandidate) -> Note | None:
    """광고가 말한 시간대의 매출 비중을 알려준다. 시점 언급이 없으면 None."""
    text = _text(copy)
    slot = next((s for s, words in TIME_WORDS.items() if any(w in text for w in words)), None)
    if slot is None or slot not in features.time_share:
        return None
    share = features.time_share[slot]
    top = max(features.time_share, key=lambda k: features.time_share[k])
    line = (
        f"광고가 {SLOT_KO[slot]}{_josa(SLOT_KO[slot], '을', '를')} 말합니다. "
        f"이 동네 {features.category_nm} 매출의 {share * 100:.0f}%가 그 시간대에 나옵니다."
    )
    if top != slot:
        line += (
            f" 가장 많이 팔리는 때는 {SLOT_KO[top]}로 {features.time_share[top] * 100:.0f}%입니다."
        )
    # 가장 많이 팔리는 시간대를 만점으로 놓고 그 대비로 잰다. LLM 점수는 이걸
    # 거의 못 갈랐다 (실측: 점심 55.0 vs 새벽 53.5, 재실행 흔들림과 같은 크기).
    top_share = features.time_share[top]
    return Note(
        kind="timing",
        text=line,
        evidence=[FeatureRef(path=f"time_share.{slot}", value=share)],
        fit=round(share / top_share, 4) if top_share > 0 else None,
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
        # 주말은 7일 중 2일이니 28.6%가 "요일 수만큼"이다. 그보다 많이 팔리면
        # 주말 광고가 맞는 동네다. 역삼 카페 0.138 → 0.48, 홍대 한식 0.44 → 1.0.
        fit=round(min(1.0, features.weekend_ratio / (2 / 7)), 4),
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


def competition_note(features: TradeAreaFeatures) -> Note:
    """경쟁 상황. 광고 문구와 무관하게 항상 나온다.

    적합도를 매기지 않는 이유: 경쟁이 많다고 광고가 틀린 것은 아니다.
    많으면 "뭐가 다른지 말해야 한다", 빠지는 중이면 다른 얘기가 된다 —
    어느 쪽이 좋고 나쁨이 아니라 사장님이 알아야 할 맥락이다.
    """
    cat = features.category_nm
    line = f"이 동네 {cat}{_josa(cat, '은', '는')} {features.competitor_cnt:,}곳입니다."
    if features.open_cnt or features.close_cnt:
        line += (
            f" 지난 분기에 {features.open_cnt}곳이 새로 열고 {features.close_cnt}곳이 닫았습니다."
        )
    return Note(
        kind="competition",
        text=line,
        evidence=[
            FeatureRef(path="competitor_cnt", value=float(features.competitor_cnt)),
            FeatureRef(path="close_cnt", value=float(features.close_cnt)),
        ],
    )


def contrast(features: TradeAreaFeatures, brief: AdBrief, copy: CopyCandidate) -> list[Note]:
    """대조 전체. 해당 없는 항목은 빠지고, 동네 구성·경쟁은 항상 들어간다."""
    notes = [
        price_note(features, brief),
        timing_note(features, copy),
        weekend_note(features, copy),
        composition_note(features),
        competition_note(features),
    ]
    return [n for n in notes if n is not None]


#: 이 값 아래여야 "어긋난다"고 말한다.
#:
#: `weakest()` 는 최솟값을 그냥 돌려주므로, 다 잘 맞는 광고에서도 하나가 뽑힌다.
#: 실제 화면에서 6,000원 광고(객단가 9,546원 → 적합도 1.0)에 "가장 어긋나는
#: 곳: 가격"이 떴다. **잘 맞는데 경고를 띄우면 나머지 경고도 안 믿게 된다.**
WEAK_FIT: Final = 0.7


def weakest(notes: list[Note]) -> Note | None:
    """가장 어긋난 항목 하나. 잴 것이 없으면 None.

    **평균을 내지 않는다.** 한 번 만들었다가 지웠는데, 항목마다 "해당 없음"이
    생기는 구조라 평균이 왜곡된다 — 실측에서 이렇게 뒤집혔다.

        "퇴근길에 하나"      시점 언급 O → 저녁 0.31 → 평균 66
        "10대 필수템 크로플"  시점 언급 X → 항목이 빠짐 → 평균 100

    **시점을 말한 광고만 감점당한다.** 사람이 보면 앞쪽이 나은 광고인데
    점수는 뒤집힌다. 항목을 말하지 않은 쪽이 유리해지는 점수는 쓸 수 없다.
    한 숫자가 필요하면 "가장 어긋난 항목"을 쓰는 편이 정직하고, 사장님도
    평균값보다 "무엇을 고칠지"를 알 수 있다.
    """
    scored = [n for n in notes if n.fit is not None]
    return min(scored, key=lambda n: n.fit or 0.0) if scored else None
