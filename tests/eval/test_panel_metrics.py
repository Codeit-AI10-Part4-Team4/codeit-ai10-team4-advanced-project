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


def test_praised_price_with_price_label_is_a_contradiction() -> None:
    """실측에서 12명이 가격이 괜찮다고 말하면서 걸림돌은 price 를 골랐다."""
    pairs = [
        ("가격은 괜찮지만, 늘 가던 곳이 있어서 고민이 됩니다", "price"),
        ("가격이 저렴해서 가볼까 싶지만, 다른 카페와 비교하게 되네요", "price"),
    ]
    assert len(price_contradictions(pairs)) == 2


def test_genuine_price_complaint_is_not_flagged() -> None:
    """정말 비싼 광고면 price 가 맞는 답이다 — 쏠림 자체는 결함이 아니다."""
    pairs = [
        ("맛있을 것 같지만 가격이 부담스럽네요", "price"),
        ("9,500원이면 한 번 더 생각하게 됩니다", "price"),
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
