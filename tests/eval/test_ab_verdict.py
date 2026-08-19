"""A/B 판정 로직 — 천장 표본을 '효과 없음'으로 세지 않는지 본다.

측정 도구가 틀리면 측정값도 틀린다. API 없이 확인할 수 있는 판정 함수만 본다.
"""

from __future__ import annotations

from run_ab_panel import verdict


def _ad(weak: float | None, scored: dict[str, float]) -> dict:
    return {"weak": weak, "scored": scored}


def test_시작점이_만점이면_잴_수_없다고_말한다() -> None:
    """`fit` 은 1.0 이 만점이라 여기서는 개선이 나올 수 없다.

    1차 측정 9건 중 6건이 이 상태였는데 '변화 없음'으로 세어져, 표만 보면 패널이
    아무 값도 못 한 것처럼 보였다. 못 잰 것과 효과 없는 것은 다르다.
    """
    before = _ad(1.0, {"price": 1.0})
    assert verdict(before, _ad(1.0, {"price": 1.0})) == "천장(잴 수 없음)"


def test_천장은_점수가_내려가도_잴_수_없음이다() -> None:
    """내려간 것은 재생성이 흔든 것이지 제안이 못 한 것이 아니다."""
    assert verdict(_ad(1.0, {"price": 1.0}), _ad(0.9, {"price": 0.9})) == "천장(잴 수 없음)"


def test_여지가_있으면_개선과_악화를_가른다() -> None:
    before = _ad(0.4, {"price": 1.0, "timing": 0.4})
    assert verdict(before, _ad(0.7, {"price": 1.0, "timing": 0.7})) == "개선"
    assert verdict(before, _ad(0.2, {"price": 1.0, "timing": 0.2})) == "악화"
    assert verdict(before, _ad(0.4, {"price": 1.0, "timing": 0.4})) == "변화 없음"


def test_항목이_사라지면_점수가_올라도_개선이_아니다() -> None:
    """시점 언급을 지우면 감점 항목째 사라져 점수가 오른다 — 회피다."""
    before = _ad(0.4, {"price": 1.0, "timing": 0.4})
    assert verdict(before, _ad(1.0, {"price": 1.0})) == "회피(timing)"
