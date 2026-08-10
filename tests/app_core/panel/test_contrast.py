"""대조 규칙 검증 — LLM 없이 도는 순수 함수다.

핵심은 두 가지다.
  1. 모든 근거가 실제 피처값과 대조를 통과하는가 (지어낸 숫자가 없는가)
  2. 동네를 바꾸면 문장이 달라지는가 (상권 데이터가 장식이 아닌가)
"""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel.contrast import (
    composition_note,
    contrast,
    price_note,
    timing_note,
    weekend_note,
)
from app_core.panel.evidence import evidence_failures
from app_core.panel.schemas import TradeAreaFeatures
from app_core.schema import AdBrief, CopyCandidate

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
    assert price_note(_features(), AdBrief(goal="copy", product="크로플", price=0)) is None


def test_객단가와_광고가격을_나란히_보여준다() -> None:
    note = price_note(_features(), BRIEF)
    assert note is not None
    assert "6,000원" in note.text  # 광고가 적은 값
    assert "9,546원" in note.text  # 동네 실측값
    assert "비쌉" not in note.text and "저렴" not in note.text  # 판정하지 않는다


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
