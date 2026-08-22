"""일치도 지표 테스트."""

from __future__ import annotations

import pytest
from panel_metrics import (
    mean_absolute_error,
    pearson,
    price_contradictions,
    spearman,
)


def test_perfect_correlation() -> None:
    assert pearson([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)


def test_perfect_inverse() -> None:
    assert pearson([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_zero_variance_returns_zero() -> None:
    assert pearson([5, 5, 5], [1, 2, 3]) == 0.0


def test_spearman_ignores_scale() -> None:
    """순위만 같으면 값의 스케일이 달라도 1.0이어야 한다."""
    assert spearman([10, 20, 30], [1, 5, 100]) == pytest.approx(1.0)


def test_spearman_handles_ties() -> None:
    assert spearman([1, 1, 2], [3, 3, 9]) == pytest.approx(1.0)


def test_mae() -> None:
    assert mean_absolute_error([70, 60], [65, 70]) == pytest.approx(7.5)


@pytest.mark.parametrize(
    ("pred", "truth"),
    [([1, 2], [1]), ([1], [1])],
)
def test_invalid_input_raises(pred: list[float], truth: list[float]) -> None:
    with pytest.raises(ValueError):
        pearson(pred, truth)


# --- 걸림돌 라벨의 자기모순 (2026-08-14) ------------------------------------
#
# 아래 코멘트는 전부 **실제 API 응답**이다. 지어낸 문장으로 테스트하면
# 계측기가 실전에서 어떻게 틀리는지 알 수 없다. 첫 판(낱말 줄기 매칭)이
# 실측에서 5건을 잡았는데 5건 다 오탐이었던 것도 그래서 못 봤다.


#: 6,000원 크로플 광고 — 광고에 가격 말고 구체적인 게 없다.
#: 12명 전원이 price 를 골랐는데, **읽어 보면 다 정당한 반응이다.**
CHEAP_AD_PRICE_ONLY = [
    "크로플이 맛있어 보이는데, 가격이 적당한지 고민이 되네요.",
    "크로플이 맛있어 보이긴 한데, 가격이 좀 더 저렴했으면 좋겠어요.",
    "크로플이 맛있을 것 같지만, 가격이 다른 카페와 비슷해서 고민하게 돼요.",
    "크로플이 맛있을 것 같지만, 가격이 조금 더 저렴했으면 좋겠어요.",
    "크로플이 맛있을 것 같지만, 가격이 조금 부담스러워서 고민이 되네요.",
    "크로플이 맛있을 것 같긴 한데, 가격이 좀 애매하네요.",
]

#: 3,000원 아메리카노 광고 — 동네 평균의 1/3 인데 price 를 골랐다.
#: 코멘트가 **가격은 괜찮다고 단정하고** 다른 이유를 댄다. 이것이 모순이다.
CHEAP_AD_REAL_REASON_ELSEWHERE = [
    "가격은 괜찮지만, 늘 가던 곳이 있어서 고민이 됩니다.",
    "가격이 매력적이긴 한데, 늘 가던 곳이 있어서 고민이 됩니다.",
    "가격이 저렴해서 가볼까 싶지만, 다른 카페와 비교하게 될 것 같아요.",
    "가격이 적당해 보이지만, 점심 시간에 가는 곳이 많아서 고민이 됩니다.",
    "가격은 괜찮은데, 늘 가던 카페가 있어서 고민이네요.",
]


def test_uncertainty_about_price_is_not_praise() -> None:
    """ "적당한지 고민" 은 "적당하다" 가 아니다 — 어미가 뜻을 뒤집는다.

    첫 판이 낱말 줄기만 봐서 이 여섯을 전부 모순으로 셌다. 5/5 오탐이었다.
    """
    pairs = [(c, "price") for c in CHEAP_AD_PRICE_ONLY]
    assert price_contradictions(pairs) == []


def test_praised_price_with_price_label_is_a_contradiction() -> None:
    """가격이 괜찮다고 단정하고 다른 이유를 대면서 라벨은 price 다."""
    pairs = [(c, "price") for c in CHEAP_AD_REAL_REASON_ELSEWHERE]
    assert len(price_contradictions(pairs)) == len(CHEAP_AD_REAL_REASON_ELSEWHERE)


def test_genuine_price_complaint_is_not_flagged() -> None:
    """정말 비싼 광고면 price 가 맞는 답이다 — 쏠림 자체는 결함이 아니다."""
    pairs = [
        ("맛있을 것 같지만 가격이 부담스럽네요", "price"),
        ("9,500원이면 한 번 더 생각하게 됩니다", "price"),
        ("가격이 좀 더 저렴했으면 좋겠어요", "price"),
    ]
    assert price_contradictions(pairs) == []


def test_other_labels_are_never_flagged() -> None:
    """가격을 칭찬했어도 걸림돌이 price 가 아니면 모순이 아니다."""
    pairs = [
        ("가격은 괜찮은데 늘 가던 곳이 있어서요", "alternative"),
        ("가격이 적당해 보이지만 정보가 부족해요", "message"),
    ]
    assert price_contradictions(pairs) == []


def test_empty_input() -> None:
    assert price_contradictions([]) == []


#: 2026-08-21 실측 — 칭찬이 **상품**을 가리키는데 가격 칭찬으로 오독했다.
#: 어미까지 봤지만 "무엇을 칭찬하는지" 는 안 보고 있었다. 두 번째 오탐이다.
PRAISES_THE_PRODUCT = [
    "평양냉면이 매력적이긴 한데, 가격이 너무 높아서 고민이 됩니다.",
    "평양냉면이 매력적이긴 한데, 가격이 18,000원이어서 부담스러워요.",
    "크로플이 맛있어 보이는데, 가격이 적당한지 고민이 되네요.",
]


def test_praise_of_the_product_is_not_praise_of_the_price() -> None:
    """ "평양냉면이 매력적" 은 가격 칭찬이 아니다.

    절을 나눠 **같은 절 안에 가격 말과 칭찬이 함께 있을 때만** 센다.
    "A 는 매력적인데, 가격이 높다" 는 두 절이 각각 하나씩만 갖는다.
    """
    pairs = [(c, "price") for c in PRAISES_THE_PRODUCT]
    assert price_contradictions(pairs) == []


def test_praise_of_the_price_still_caught() -> None:
    """가격을 가리키며 괜찮다고 한 것은 그대로 잡는다."""
    pairs = [(c, "price") for c in CHEAP_AD_REAL_REASON_ELSEWHERE]
    assert len(price_contradictions(pairs)) == len(CHEAP_AD_REAL_REASON_ELSEWHERE)
