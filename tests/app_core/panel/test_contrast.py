"""대조 규칙 검증 — LLM 없이 도는 순수 함수다.

핵심은 두 가지다.
  1. 모든 근거가 실제 피처값과 대조를 통과하는가 (지어낸 숫자가 없는가)
  2. 동네를 바꾸면 문장이 달라지는가 (상권 데이터가 장식이 아닌가)
"""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel.contrast import (
    competition_note,
    composition_note,
    contrast,
    price_note,
    price_visible,
    timing_note,
    weakest,
    weekend_note,
)
from app_core.panel.evidence import evidence_failures
from app_core.panel.schemas import TradeAreaFeatures
from app_core.schema import AdBrief, CopyCandidate, Store

BRIEF = AdBrief(goal="copy", product="크로플", price=6000)


def _features(**over: Any) -> TradeAreaFeatures:
    base: dict[str, Any] = {
        "area_cd": "A1",
        "area_nm": "역삼역",
        "area_type": "발달상권",
        "gu_nm": "강남구",
        "dong_nm": "역삼1동",
        "quarter": "20261",
        "category_nm": "커피-음료",
        "gender_share": {"M": 0.49, "F": 0.51},
        "age_share": {"10": 0.02, "20": 0.16, "30": 0.4, "40": 0.2, "50": 0.15, "60": 0.07},
        "demo_coverage": 0.71,
        "time_share": {
            "00-06": 0.01,
            "06-11": 0.15,
            "11-14": 0.48,
            "14-17": 0.19,
            "17-21": 0.15,
            "21-24": 0.02,
        },
        "foot_age_share": {"10": 0.08, "20": 0.3, "30": 0.28, "40": 0.18, "50": 0.1, "60": 0.06},
        "weekend_ratio": 0.138,
        "avg_ticket": 9546,
        "avg_ticket_pct": 0.674,
        "competitor_cnt": 185,
    }
    return TradeAreaFeatures(**{**base, **over})


def test_근거가_전부_실제값과_일치한다() -> None:
    """지어낸 숫자가 하나도 없어야 한다 — 이게 A 등급의 조건이다."""
    f = _features()
    copy = CopyCandidate(headline="점심 후 달달한 크로플", sub="주말에도 만나요")
    for note in contrast(f, BRIEF, copy):
        assert not evidence_failures(f, note.evidence), note.kind


def test_가격을_안_적으면_가격_대조가_없다() -> None:
    zero = AdBrief(goal="copy", product="크로플", price=0)
    assert price_note(_features(), zero, CopyCandidate(headline="크로플 6,000원")) is None
    # 가격을 정했어도 문구에 안 실리면 견줄 것이 없다 (2026-08-20)
    assert price_note(_features(), BRIEF, CopyCandidate(headline="갓 구운 크로플")) is None


def test_객단가와_광고가격을_나란히_보여준다() -> None:
    note = price_note(_features(), BRIEF, CopyCandidate(headline="크로플 6,000원"))
    assert note is not None
    assert "6,000원" in note.text  # 광고가 적은 값
    assert "9,546원" in note.text  # 동네 실측값
    assert "비쌉" not in note.text and "저렴" not in note.text  # 판정하지 않는다


def test_광고에_금액이_보일_때만_가격이_보인다() -> None:
    """`show_price` 는 "입력했나"만 본다 — 문구에 실렸는지는 여기서 본다.

    2026-08-20 실측: 가격만 바꾼 포스터 세 장 어디에도 금액이 없었는데
    패널은 `price` 비중을 5.6% / 66.7% / 100% 로 갈랐다. 손님이 못 보는 값으로
    판정한 것이다.
    """
    brief = AdBrief(goal="copy", product="크로플", price=6000)

    assert price_visible(brief, CopyCandidate(headline="크로플 6,000원"))
    assert price_visible(brief, CopyCandidate(headline="갓 구운 크로플", sub="6,000원"))

    # 금액이 아예 없다 — 지금 대부분의 문구가 이 경우다
    assert not price_visible(brief, CopyCandidate(headline="점심 10분 컷, 크로플"))
    # 사장님이 정한 적 없는 금액이다 (price_text_note ③ 가 따로 짚는다)
    assert not price_visible(brief, CopyCandidate(headline="크로플 8,900원"))
    # 정한 값이 있어도 **다른 금액이 섞이면** 닫는다 (귀한님 지적, PR #50 리뷰)
    assert not price_visible(brief, CopyCandidate(headline="크로플 6,000원, 원래 8,900원"))
    # 한글 단위 금액도 읽는다 — "1만 5천원" 을 15,000 하나로 본다
    pricey = AdBrief(goal="copy", product="크로플", price=15000)
    assert price_visible(pricey, CopyCandidate(headline="크로플 1만 5천원"))
    assert not price_visible(pricey, CopyCandidate(headline="크로플 5천원"))
    # 가격을 빼기로 한 광고
    assert not price_visible(
        AdBrief(goal="copy", product="크로플", price=0),
        CopyCandidate(headline="크로플 6,000원"),
    )


def test_시점을_말하지_않으면_시간_대조가_없다() -> None:
    assert timing_note(_features(), CopyCandidate(headline="갓 구운 크로플")) is None


def test_광고가_말한_시간대의_매출을_알려준다() -> None:
    note = timing_note(_features(), CopyCandidate(headline="저녁에 오세요"))
    assert note is not None
    assert "저녁" in note.text
    assert "15%" in note.text  # time_share["17-21"]
    assert "점심" in note.text  # 가장 많이 팔리는 때도 같이


def test_가장_많이_팔리는_때를_말하면_반복하지_않는다() -> None:
    note = timing_note(_features(), CopyCandidate(headline="점심 후 크로플"))
    assert note is not None
    assert note.text.count("점심") == 1


def test_주말을_말할_때만_주말_대조가_나온다() -> None:
    assert weekend_note(_features(), CopyCandidate(headline="갓 구운 크로플")) is None
    note = weekend_note(_features(), CopyCandidate(headline="주말 한정"))
    assert note is not None
    assert "14%" in note.text


def test_동네_구성은_판정하지_않고_사실만_말한다() -> None:
    note = composition_note(_features())
    assert "30대가 40%" in note.text
    assert "여성이 51%" in note.text
    assert "사장님이 정하시면" in note.text


def test_동네를_바꾸면_문장이_달라진다() -> None:
    """반증 테스트 — 상권 데이터가 장식이 아님을 보인다."""
    copy = CopyCandidate(headline="저녁에 오세요")
    a = contrast(_features(), BRIEF, copy)
    b = contrast(
        _features(
            category_nm="한식음식점",
            avg_ticket=30635,
            avg_ticket_pct=0.91,
            age_share={"10": 0.03, "20": 0.42, "30": 0.3, "40": 0.14, "50": 0.08, "60": 0.03},
            time_share={
                "00-06": 0.04,
                "06-11": 0.05,
                "11-14": 0.2,
                "14-17": 0.14,
                "17-21": 0.42,
                "21-24": 0.15,
            },
        ),
        BRIEF,
        copy,
    )
    assert [n.text for n in a] != [n.text for n in b]


def test_대조는_같은_입력에_같은_출력이다() -> None:
    f, copy = _features(), CopyCandidate(headline="주말 저녁에 오세요")
    assert contrast(f, BRIEF, copy) == contrast(f, BRIEF, copy)


@pytest.mark.parametrize("word", ["아침", "점심", "오후", "저녁", "야식"])
def test_시점_단어를_알아챈다(word: str) -> None:
    assert timing_note(_features(), CopyCandidate(headline=f"{word}에 드세요")) is not None


def test_적합도는_해당되는_항목에만_붙는다() -> None:
    f = _features()
    # 금액은 실려 있어야 가격 대조가 붙는다 (2026-08-20 `price_visible`)
    plain = CopyCandidate(headline="크로플 6,000원")  # 시점·주말 언급 없음
    kinds = {n.kind: n.fit for n in contrast(f, BRIEF, plain)}
    assert kinds["price"] is not None
    assert "timing" not in kinds and "weekend" not in kinds
    assert kinds["composition"] is None  # 타깃을 모르니 적합도를 못 매긴다


def test_비싼_쪽만_감점한다() -> None:
    """객단가는 결제 1건 평균이라 품목 하나가 그보다 싼 건 정상이다."""
    f = _features()  # avg_ticket 9546

    def fit(price: int) -> float | None:
        brief = AdBrief(goal="copy", product="크로플", price=price)
        note = price_note(f, brief, CopyCandidate(headline=f"크로플 {price:,}원"))
        return note.fit if note else None

    assert fit(2000) == 1.0
    assert fit(9500) == 1.0
    assert fit(45000) is not None and fit(45000) < 0.3  # 4.7배


def test_새벽을_알아챈다() -> None:
    """00-06 을 TIME_WORDS 에 빠뜨려 '새벽 감성 크로플'이 미언급으로 처리됐었다."""
    note = timing_note(_features(), CopyCandidate(headline="새벽 감성 크로플"))
    assert note is not None
    # 적합도는 가장 많이 팔리는 시간대 대비다 — 0.01 / 0.48 = 0.02
    assert note.fit is not None and note.fit < 0.05


def test_상품명이_빠지면_짚어준다() -> None:
    from app_core.panel.contrast import product_note

    brief = BRIEF.model_copy(update={"product": "크로플 세트"})
    assert product_note(brief, CopyCandidate(headline="달콤한 오후를 만나보세요")) is not None
    # 여러 낱말이면 하나만 나와도 말한 것으로 본다
    assert product_note(brief, CopyCandidate(headline="크로플, 지금 만나보세요")) is None


def test_근거_없는_최상급을_짚어준다() -> None:
    """`copy_gen` 이 쓰지 말라고 지시하는데 아무도 검사하지 않고 있었다."""
    from app_core.panel.contrast import claim_note

    note = claim_note(CopyCandidate(headline="이 동네 최고의 크로플"))
    assert note is not None and "최고" in note.text
    assert claim_note(CopyCandidate(headline="갓 구운 크로플")) is None


def test_상호에_든_말은_주장으로_보지_않는다() -> None:
    from app_core.panel.contrast import claim_note

    store = Store(id=1, user_id=1, industry="cafe", name="제일커피", address="서울 강남구")
    assert claim_note(CopyCandidate(headline="제일커피의 크로플"), store) is None
    assert claim_note(CopyCandidate(headline="제일커피의 크로플"), None) is not None


def test_지어낸_금액을_짚어준다() -> None:
    """사장님이 정한 값이 아니면 지어낸 것으로 본다 — `copy_gen` 과 같은 규칙이다."""
    from app_core.panel.contrast import price_text_note

    brief = BRIEF.model_copy(update={"price": 8900})
    note = price_text_note(brief, CopyCandidate(headline="크로플 6,000원"))
    assert note is not None and "6,000원" in note.text and "8,900원" in note.text
    assert price_text_note(brief, CopyCandidate(headline="크로플 8,900원")) is None


def test_가격을_빼기로_했는데_적히면_짚어준다() -> None:
    from app_core.panel.contrast import price_text_note

    brief = BRIEF.model_copy(update={"price": 0})
    assert price_text_note(brief, CopyCandidate(headline="크로플 5,000원")) is not None
    assert price_text_note(brief, CopyCandidate(headline="갓 구운 크로플")) is None


def test_문구_결함은_적합도를_받지_않는다() -> None:
    """`fit` 은 '이 동네와 얼마나 맞나'다. 상품명 누락은 동네와 상관이 없다.

    섞으면 `weakest()` 가 결함을 '가장 어긋나는 곳'으로 뽑아 동네 대조를 가린다.
    """
    from app_core.panel.contrast import DEFECT_KINDS, copy_defects

    copy = CopyCandidate(
        headline="이 동네 최고", sub="9,900원"
    )  # BRIEF 는 6,000원이다  # 결함 3종 전부
    defects = copy_defects(BRIEF, copy)
    assert {n.kind for n in defects} == DEFECT_KINDS
    assert all(n.fit is None for n in defects)
    assert weakest(defects) is None  # 잴 것이 없으므로 고를 것도 없다


def test_문구_결함은_동네_대조에_섞이지_않는다() -> None:
    """근거 관문이 '모든 대조 문장은 수치를 인용한다'를 계약으로 걸어두었다.

    결함 문장은 인용할 수치가 없어 `evidence` 가 빈다 — 합칠지는 수호님 판단이라
    `contrast()` 에 넣지 않았다.
    """
    from app_core.panel.contrast import DEFECT_KINDS

    copy = CopyCandidate(headline="이 동네 최고", sub="9,900원")  # BRIEF 는 6,000원이다
    notes = contrast(_features(), BRIEF, copy)
    assert not [n for n in notes if n.kind in DEFECT_KINDS]
    assert all(n.evidence for n in notes)  # 전부 수치를 인용한다


def test_간식은_시점이_아니다() -> None:
    """A/B 측정에서 "특별한 간식!" 이 오후 광고로 잡혀 적합도 0.40 이 붙었다.

    끼니말(점심·저녁·야식)과 달리 간식은 때를 가리키지 않는다. 사장님이
    시간대를 말한 적이 없는데 시간대로 감점당하면 안 된다.
    """
    copy = CopyCandidate(headline="크로플 세트", sub="8,900원으로 즐기는 특별한 간식!")
    assert timing_note(_features(), copy) is None


def test_가장_어긋난_항목을_고른다() -> None:
    f = _features()
    copy = CopyCandidate(headline="새벽 감성 크로플")  # 시점이 최악, 가격은 정상
    w = weakest(contrast(f, BRIEF, copy))
    assert w is not None and w.kind == "timing"


def test_잴_것이_없으면_None_이다() -> None:
    """0점과 '못 잼'은 다르다."""
    f = _features()
    brief = AdBrief(goal="copy", product="크로플", price=0)  # 가격 미표기
    assert weakest(contrast(f, brief, CopyCandidate(headline="갓 구운 크로플"))) is None


def test_경쟁은_숫자만_주고_판정하지_않는다() -> None:
    """경쟁이 많다고 광고가 틀린 것은 아니다 — 맥락이지 점수가 아니다."""
    note = competition_note(_features(competitor_cnt=176, open_cnt=0, close_cnt=2))
    assert "176곳" in note.text
    assert "2곳이 닫았습니다" in note.text
    assert note.fit is None


def test_개폐업이_0이면_그_문장을_빼다() -> None:
    note = competition_note(_features(competitor_cnt=176, open_cnt=0, close_cnt=0))
    assert "176곳" in note.text
    assert "닫았습니다" not in note.text


@pytest.mark.parametrize(
    ("word", "want"),
    [("커피-음료", "는"), ("한식음식점", "은"), ("치킨전문점", "은"), ("전체 업종", "은")],
)
def test_업종명_받침에_맞는_조사를_쓴다(word: str, want: str) -> None:
    """업종명이 데이터에서 오므로 조사를 미리 정해둘 수 없다."""
    note = competition_note(_features(category_nm=word, competitor_cnt=10))
    assert f"{word}{want}" in note.text


def test_새벽은_을을_쓴다() -> None:
    """'새벽를 말합니다' 로 나오던 것."""
    note = timing_note(_features(), CopyCandidate(headline="새벽 감성 크로플"))
    assert note is not None and "새벽을 말합니다" in note.text


def test_결과에_실을_때_적합도가_빠지지_않는다() -> None:
    """`Note` → `ContrastNote` 변환에서 fit 이 누락돼 화면이 죽었다.

    테스트 391개가 통과하는데도 실제 화면에서만 터졌다 — 여기서 막는다.
    """
    from app_core.panel.schemas import ContrastNote

    for n in contrast(_features(), BRIEF, CopyCandidate(headline="새벽 감성 크로플")):
        moved = ContrastNote(kind=n.kind, text=n.text, evidence=list(n.evidence), fit=n.fit)
        assert moved.fit == n.fit, n.kind


def test_잘_맞는_광고에는_경고를_띄우지_않는다() -> None:
    """weakest 는 최솟값을 그냥 준다 — 다 잘 맞아도 하나가 뽑힌다.

    실제 화면에서 6,000원 광고(객단가 9,546원 → 적합도 1.0)에
    "가장 어긋나는 곳: 가격"이 떴다. 화면은 WEAK_FIT 으로 한 번 더 거른다.
    """
    from app_core.panel.contrast import WEAK_FIT

    cheap = weakest(contrast(_features(), BRIEF, CopyCandidate(headline="크로플 6,000원")))
    assert cheap is not None and cheap.fit == 1.0
    assert cheap.fit >= WEAK_FIT  # → 화면이 강조하지 않는다

    off = weakest(contrast(_features(), BRIEF, CopyCandidate(headline="새벽 감성 크로플 6,000원")))
    assert off is not None and off.fit is not None
    assert off.fit < WEAK_FIT  # → 강조한다
