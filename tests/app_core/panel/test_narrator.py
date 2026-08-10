"""narrator 검증 — 실제 API 는 부르지 않는다 (AGENTS.md: 외부 호출은 mock)."""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel import narrator
from app_core.panel.narrator import build_prompt, narrate
from app_core.panel.panel_builder import build_panel

FEATURES: dict[str, Any] = {
    "area_nm": "역삼역",
    "area_type": "발달상권",
    "gu_nm": "강남구",
    "dong_nm": "역삼1동",
    "category_nm": "커피-음료",
    "gender_share": {"M": 0.5, "F": 0.5},
    "age_share": {"10": 0.02, "20": 0.16, "30": 0.4, "40": 0.2, "50": 0.15, "60": 0.07},
    "foot_age_share": {"10": 0.08, "20": 0.3, "30": 0.28, "40": 0.18, "50": 0.1, "60": 0.06},
    "back_age_share": None,
    "time_share": {
        "00-06": 0.01,
        "06-11": 0.15,
        "11-14": 0.45,
        "14-17": 0.19,
        "17-21": 0.18,
        "21-24": 0.02,
    },
    "weekend_ratio": 0.138,
    "avg_ticket": 9546,
    "avg_ticket_pct": 0.674,
    "competitor_cnt": 185,
    "work_ratio": 0.936,
}


@pytest.fixture
def personas() -> list[dict[str, Any]]:
    return build_panel(FEATURES)


def test_프롬프트에_연령별_구매_비율이_들어간다(personas: list[dict[str, Any]]) -> None:
    """축(price_sens·motive)이 상권 단위라 전원 같다. 이 비율이 유일한 구별 재료다."""
    prompt = build_prompt(personas, FEATURES)
    assert "많이 산다" in prompt  # 30대: 0.40/0.28 = 1.4배
    assert "적게 산다" in prompt  # 20대: 0.16/0.30 = 0.5배


def test_구별에_기여하지_않는_축은_넣지_않는다(personas: list[dict[str, Any]]) -> None:
    """motive·price_sens 는 상권 단위라 12명이 전원 같다 (실측: 상권 300곳 중
    82%가 exploratory). 서사에 넣으면 앞뒤가 안 맞는 문장만 나온다."""
    prompt = build_prompt(personas, FEATURES)
    assert "늘 가던 곳" not in prompt
    assert "가격 저항" not in prompt


def test_프롬프트는_12명을_한_번에_넘긴다(personas: list[dict[str, Any]]) -> None:
    prompt = build_prompt(personas, FEATURES)
    assert all(p["persona_id"] in prompt for p in personas)
    assert prompt.count("- p") == 12


def test_모델이_답을_빠뜨리면_사실_나열로_채운다(
    personas: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """서사가 비어도 평가는 돌아야 한다 — 서사는 근거가 아니다(07 §4.6 C 등급)."""

    class Partial:
        def complete_json(self, system: str, user: str) -> dict:
            return {"p01": "첫 손님 이야기"}  # 나머지 11명은 누락

    monkeypatch.setattr(narrator, "get_client", lambda: Partial())
    texts = narrate(personas, FEATURES)
    assert texts[0] == "첫 손님 이야기"
    assert all(t for t in texts[1:])  # 빈 문자열이 없다
    assert "역삼역" in texts[1]  # 사실 나열 폴백


def test_스텁_프로필에서도_죽지_않는다(
    personas: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_PROFILE", "stub")
    texts = narrate(personas, FEATURES)
    assert len(texts) == 12
    assert all(t for t in texts)
