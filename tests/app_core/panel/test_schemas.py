"""스키마 계약 테스트 — A가 넘겨주는 형식이 깨지면 여기서 잡힌다."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from app_core.panel.schemas import METRIC_FIELDS, Panel, PersonaEval, TradeAreaFeatures


def test_golden_fixture_parses(yeoksam: Panel) -> None:
    assert yeoksam.features.area_nm == "역삼역"
    assert yeoksam.features.category == "cafe"
    assert len(yeoksam.personas) == 12


def test_shares_sum_to_one(yeoksam: Panel) -> None:
    assert sum(yeoksam.features.sales_share.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(yeoksam.features.time_traffic.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(p.weight for p in yeoksam.personas) == pytest.approx(1.0, abs=1e-9)


def test_persona_weights_decompose_sales_share(yeoksam: Panel) -> None:
    """페르소나 가중치 합이 성별·연령 매출 비중과 일치해야 한다.

    A 영역의 세그먼트 분해가 어긋나면 가중 평균이 상권 구성을 반영하지 못한다.
    """
    by_cell: dict[str, float] = {}
    for persona in yeoksam.personas:
        cell = next(
            ref.path.split(".", 1)[1]
            for ref in persona.evidence
            if ref.path.startswith("sales_share.")
        )
        by_cell[cell] = by_cell.get(cell, 0.0) + persona.weight

    for cell, share in yeoksam.features.sales_share.items():
        assert by_cell[cell] == pytest.approx(share, abs=1e-9), cell


def test_boundary_personas_exist(yeoksam: Panel) -> None:
    """경계 페르소나가 없으면 저항 요인 다양성이 사라진다."""
    boundary = [p for p in yeoksam.personas if p.is_boundary]
    assert boundary, "경계 페르소나가 최소 1명은 있어야 한다"
    assert all(p.weight <= 0.05 for p in boundary)


def test_time_axis_accepts_five_values(yeoksam: Panel) -> None:
    """stage2 초안은 3종이었으나 실제 산출은 5종이다 (morning·afternoon 추가).

    enum을 좁히면 이 픽스처가 파싱 단계에서 터진다.
    """
    used = {p.axes.time for p in yeoksam.personas}
    assert {"morning", "afternoon"} <= used


def test_duplicate_persona_id_rejected(yeoksam_raw: dict[str, Any]) -> None:
    data = copy.deepcopy(yeoksam_raw)
    data["personas"][1]["persona_id"] = data["personas"][0]["persona_id"]
    with pytest.raises(ValidationError, match="중복"):
        Panel.model_validate(data)


def test_weight_sum_mismatch_rejected(yeoksam_raw: dict[str, Any]) -> None:
    data = copy.deepcopy(yeoksam_raw)
    data["personas"][0]["weight"] = 0.9
    with pytest.raises(ValidationError, match="weight 합"):
        Panel.model_validate(data)


def test_share_sum_mismatch_rejected(yeoksam_raw: dict[str, Any]) -> None:
    data = copy.deepcopy(yeoksam_raw)
    data["features"]["sales_share"]["M30"] = 0.5
    with pytest.raises(ValidationError, match="비중 합"):
        Panel.model_validate(data)


def test_fallback_defaults_to_false(yeoksam: Panel) -> None:
    """A가 아직 필드를 안 넣어도 파싱은 되고, 기본값은 '매칭 성공'이다."""
    assert yeoksam.features.is_fallback is False
    assert yeoksam.features.match_distance_m is None


def test_fallback_roundtrip() -> None:
    features = TradeAreaFeatures(
        area_cd="0",
        area_nm="서울 평균",
        dong_nm="-",
        quarter="2025Q4",
        category="cafe",
        sales_share={"M30": 0.5, "F30": 0.5},
        time_traffic={"11-14": 1.0},
        weekend_ratio=0.2,
        avg_ticket=6000,
        competitor_cnt=0,
        is_fallback=True,
        match_distance_m=1200.0,
    )
    assert features.is_fallback


def test_persona_eval_rejects_empty_evidence() -> None:
    with pytest.raises(ValidationError):
        PersonaEval(
            persona_id="p01",
            attention=50,
            message=50,
            intent=50,
            resistance="price",
            comment="비싸다",
            evidence=[],
        )


def test_persona_eval_metrics_keys() -> None:
    ev = PersonaEval(
        persona_id="p01",
        attention=10,
        message=20,
        intent=30,
        resistance="none",
        comment="괜찮다",
        evidence=[{"path": "avg_ticket", "value": 6800}],  # type: ignore[list-item]
    )
    assert set(ev.metrics()) == set(METRIC_FIELDS)
