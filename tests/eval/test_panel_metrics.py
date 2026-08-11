"""일치도 지표 테스트."""

from __future__ import annotations

import pytest
from panel_metrics import mean_absolute_error, pearson, spearman


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
