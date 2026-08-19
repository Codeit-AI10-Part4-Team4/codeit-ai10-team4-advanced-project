"""LLM 없이 광고에 대해 말할 수 있는 것. 두 종류가 있다.

**동네 대조** — 광고가 **실제로 쓴 말**과 이 동네의 **실측 수치**를 나란히 놓는다.
모든 문장이 서울시 원본에서 뺄셈·나눗셈으로 나온다 — 근거 등급 A 다.

**문구 점검**(`DEFECT_KINDS`) — 동네와 무관하게 문구만 보고 잡는 결함. 상품명이
빠졌는지, 근거 없는 최상급을 썼는지, 적힌 금액이 사장님이 정한 값과 다른지.
여기엔 동네 수치가 안 들어가므로 `fit` 을 매기지 않는다.

둘 다 LLM 이 없다. 순수 함수라 같은 입력이면 항상 같은 출력이다.

**이게 유일하게 무시당하지 않는 경로다.** 실측(2026-08-12): 프롬프트에 지시를
넣어도 모델이 안 따르는 사례를 셋 확인했다 — "60점대에 몰아 쓰지 마라"(50점대에
몰림), "평균과 비슷하면 price 가 아니다"(절반인데 price), "최고·1위 쓰지
마라"(검사 코드 0건). 지시는 있고 검증은 없었다.

**판정하지 않는다.** "이 광고는 틀렸습니다"라고 말하지 않고 "광고는 X 라 하고
이 동네는 Y 입니다"까지만 쓴다. 이유가 둘 있다.

1. 광고가 겨냥한 손님을 우리는 모른다. 주문서(`AdBrief`)에 타깃 칸이 없고,
   말투로 짐작하는 것은 독해가 아니라 추측이라 근거로 쓸 수 없다.
2. 안다 해도 "동네 다수와 다르다 = 잘못됐다"가 아니다. 경쟁이 없는 층을
   노린 전략일 수 있는데 데이터는 그 둘을 구분하지 못한다.

그래서 판단은 사장님이 한다. 우리는 숫자만 갖다 놓는다.
"""

from __future__ import annotations

import re
from math import log2
from typing import Final, NamedTuple

from app_core.panel.schemas import FeatureRef, TradeAreaFeatures
from app_core.schema import AdBrief, CopyCandidate, Store

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

    ⚠️ **분위를 말할 때 무엇의 순위인지 반드시 적는다.** 전에는
    `"서울 같은 업종 중 상위 43% 수준입니다"` 였는데, 주어도 없고 무엇의
    순위인지도 없었다. 모델이 그 빈칸을 **품질**로 채웠다 (실측 2026-08-19,
    A/B 재측정 중 제안에 그대로 나왔다):

        "서울 한식업종 상위 43%의 품질을 자랑하는 제육볶음 정식"

    가격 분위가 품질 주장으로 둔갑한 것이고, 사장님이 말한 적 없는 사실이라
    #23 이 금지한 그것이다. `SUMMARY_SYSTEM` 에 금지 지시가 이미 있는데도
    뚫렸다 — 수호님 `prompt_lint.py` 가 적어둔 대로 **모델은 금지를 안 읽는다.**
    그래서 금지를 세게 쓰는 대신 **문장에서 빈칸을 없앤다.**
    """
    if not brief.show_price:
        return None
    pct = round(features.avg_ticket_pct * 100)
    return Note(
        kind="price",
        text=(
            f"광고에 적은 가격은 {brief.price:,}원입니다. "
            f"이 동네 {features.category_nm} 결제 1건의 평균은 {features.avg_ticket:,}원입니다. "
            f"그 동네 평균값은 서울 같은 업종 상권들 중 비싼 쪽으로 상위 {100 - pct}% 입니다 "
            "— 가격 순위이지 품질 순위가 아닙니다. "
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


#: 동네 실측과 **무관하게** 문구만 보고 잡는 결함들.
#:
#: `fit` 을 주지 않는다. `fit` 은 "이 동네와 얼마나 맞나"인데 상품명 누락은 동네와
#: 상관이 없다. 한 척도에 섞으면 지어낸 계수가 되고, `weakest()` 가 "가장 어긋나는
#: 곳"으로 결함을 뽑아 동네 대조를 가려버린다. 그래서 **개수로 세는 쪽**으로 뒀다 —
#: 결정적이고 지어낸 숫자가 없다.
DEFECT_KINDS: Final = frozenset({"product", "claim", "price_text"})

#: 근거 없이 쓰면 표시광고법에 걸리는 말.
#: `copy_gen` 의 프롬프트가 "쓰지 마라"고 지시하지만 **아무도 검사하지 않는다**
#: (실측 2026-08-12: 검사 코드 0건, `CopyCandidate` 는 헤드라인이 비었는지만 본다).
CLAIM_WORDS: Final = ("최고", "최상", "1위", "일위", "최초", "제일", "유일", "넘버원", "No.1")

_AMOUNT_RE: Final = re.compile(r"(\d[\d,]*)\s*원")


def product_note(brief: AdBrief, copy: CopyCandidate) -> Note | None:
    """문구가 **무엇을 파는지** 말하는가.

    "크로플 세트" 처럼 여러 낱말이면 하나만 나와도 말한 것으로 본다. 한 글자
    낱말("차", "국")은 아무 문장에나 걸려서 세지 않는다.
    """
    tokens = [t for t in brief.product.split() if len(t) >= 2]
    if not tokens or any(t in _text(copy) for t in tokens):
        return None
    return Note(
        kind="product",
        text=(
            f'광고에 "{brief.product}"라는 말이 없습니다. '
            "문구만 보고는 무엇을 파는지 알 수 없습니다."
        ),
        evidence=[],
    )


def claim_note(copy: CopyCandidate, store: Store | None = None) -> Note | None:
    """근거 없는 최상급 표현. 상호에 든 말은 주장이 아니므로 뺀다."""
    text = _text(copy)
    if store is not None:
        # "제일식당"·"최고집" 같은 상호를 주장으로 오인하지 않는다
        text = text.replace(store.name, " ")
    found = next((w for w in CLAIM_WORDS if w in text), None)
    if found is None:
        return None
    return Note(
        kind="claim",
        text=(
            f'광고가 "{found}"라고 말합니다. 뒷받침할 자료가 없으면 표시광고법에 '
            "걸릴 수 있어, 근거를 대실 수 없다면 빼는 편이 안전합니다."
        ),
        evidence=[],
    )


def price_text_note(brief: AdBrief, copy: CopyCandidate) -> Note | None:
    """문구에 적힌 금액이 사장님이 정한 것과 맞는가.

    셋 다 사장님이 모르고 지나가면 곤란한 경우다.
      ① 가격을 빼기로 했는데 금액이 적혔다
      ② 가격을 넣기로 했는데 금액이 없다
      ③ **정한 적 없는 금액이 적혔다** — 지어낸 가격이라 가장 위험하다

    ③ 의 판정 규칙은 `evaluator._summarize` 의 금액 가드와 같다: 사장님이 준
    값이 아니면 전부 지어낸 것으로 본다. `copy_gen` 도 "가격은 사장님이 입력한
    값만 쓴다"고 적어두었다.

    ⚠️ **② 는 셋 중 가장 약하다.** 가격을 입력했다고 문구에 꼭 넣어야 하는 것은
    아니고 `copy_gen` 도 "넣어라"고 지시하지 않는다. 실측(2026-08-12, 생성된 문구
    27개): ② 가 3건, ①·③ 은 0건이었다. 그래서 문장을 "빠졌습니다"가 아니라
    "없습니다"로 두었다 — 이 파일의 "판정하지 않는다" 원칙 그대로다. 사장님이
    귀찮아하면 ② 만 빼면 된다.
    """
    amounts = {int(m.replace(",", "")) for m in _AMOUNT_RE.findall(_text(copy))}
    if not brief.show_price:
        if not amounts:
            return None
        return Note(
            kind="price_text",
            text=(
                "사장님은 가격을 빼기로 하셨는데 광고에 "
                f"{', '.join(f'{a:,}원' for a in sorted(amounts))}이 적혀 있습니다."
            ),
            evidence=[],
        )
    if not amounts:
        return Note(
            kind="price_text",
            text=f"가격을 {brief.price:,}원으로 정하셨는데 문구에는 금액이 없습니다.",
            evidence=[],
        )
    wrong = sorted(amounts - {brief.price})
    if not wrong:
        return None
    return Note(
        kind="price_text",
        text=(
            f"광고에 {', '.join(f'{a:,}원' for a in wrong)}이 적혀 있는데 "
            f"사장님이 정하신 값은 {brief.price:,}원입니다. 없는 가격을 쓰면 안 됩니다."
        ),
        evidence=[],
    )


def copy_defects(brief: AdBrief, copy: CopyCandidate, store: Store | None = None) -> list[Note]:
    """문구만 보고 잡는 결함들. **`contrast()` 와 일부러 분리했다.**

    `contrast()` 의 문장은 전부 상권 수치를 인용하고, `evaluator` 의 근거 관문이
    그 인용을 검증한다(`test_contrast_notes_survive_the_evidence_gate` 가 계약으로
    걸어둔 것이다). 여기 문장들은 인용할 수치가 없어 `evidence` 가 비고, 그러면
    그 관문에 걸린다.

    빈 근거를 "주장한 게 없으니 검증할 것도 없다"로 볼지는 관문을 만드신 수호님이
    정할 일이라, 밀어 넣지 않고 따로 뒀다. 합치기로 하면 `contrast()` 안에서
    부르기만 하면 된다.

    `store` 는 상호에 든 최상급 표현을 걸러내는 데만 쓴다.
    """
    notes = [
        product_note(brief, copy),
        claim_note(copy, store),
        price_text_note(brief, copy),
    ]
    return [n for n in notes if n is not None]


def contrast(features: TradeAreaFeatures, brief: AdBrief, copy: CopyCandidate) -> list[Note]:
    """동네 대조 전체. 해당 없는 항목은 빠지고, 동네 구성·경쟁은 항상 들어간다.

    문구 자체의 결함은 여기 없다 — `copy_defects()` 를 따로 부른다(이유는 그쪽).
    """
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
