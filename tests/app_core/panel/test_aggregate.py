"""가중 집계 테스트."""

from __future__ import annotations

import pytest

from app_core.panel.aggregate import AggregationError, aggregate
from app_core.panel.schemas import FeatureRef, Panel, Persona, PersonaEval

AD_ID = "ad-001"


def _eval(
    persona: Persona,
    *,
    attention: int = 60,
    message: int = 60,
    intent: int = 60,
    resistance: str = "none",
    evidence: list[FeatureRef] | None = None,
) -> PersonaEval:
    return PersonaEval(
        persona_id=persona.persona_id,
        attention=attention,
        message=message,
        intent=intent,
        resistance=resistance,  # type: ignore[arg-type]
        comment=f"{persona.demo} 코멘트",
        evidence=list(persona.evidence) if evidence is None else evidence,
    )


def _all_valid(panel: Panel, **kw: int | str) -> list[PersonaEval]:
    return [_eval(p, **kw) for p in panel.personas]  # type: ignore[arg-type]


def test_uniform_scores(yeoksam: Panel) -> None:
    result = aggregate(
        yeoksam, _all_valid(yeoksam, attention=70, message=70, intent=70), ad_id=AD_ID
    )
    assert result.ad_id == AD_ID
    assert result.scores == {"attention": 70.0, "message": 70.0, "intent": 70.0}
    assert result.confidence == "ok"
    assert result.confidence_reasons == []
    assert result.max_metric_std == 0.0
    assert result.excluded_cnt == 0


def test_provenance_is_carried(yeoksam: Panel) -> None:
    """결과 화면이 '무엇을 근거로 한 평가인지' 표시할 수 있어야 한다."""
    result = aggregate(yeoksam, _all_valid(yeoksam), ad_id=AD_ID)
    assert result.area_nm == "역삼역"
    assert result.quarter == "20261"
    assert result.is_fallback is False
    assert result.demo_coverage == pytest.approx(0.714)


def test_suggestions_are_passed_through(yeoksam: Panel) -> None:
    """집계는 제안을 만들지 않는다 — 요약 콜 결과를 실어 나르기만 한다."""
    given = ["가격을 묶음가로 제시", "점심 시간대를 문구에 넣기"]
    result = aggregate(yeoksam, _all_valid(yeoksam), ad_id=AD_ID, suggestions=given)
    assert result.suggestions == given
    assert aggregate(yeoksam, _all_valid(yeoksam), ad_id=AD_ID).suggestions == []


def test_boundary_excluded_from_scores_but_kept_in_comments(yeoksam: Panel) -> None:
    boundary = [p for p in yeoksam.personas if p.is_boundary]
    evals = [_eval(p, attention=0 if p.is_boundary else 80) for p in yeoksam.personas]
    result = aggregate(yeoksam, evals, ad_id=AD_ID)

    assert result.scores["attention"] == 80.0
    assert set(result.boundary_excluded_ids) == {p.persona_id for p in boundary}
    commented = {c.persona_id for c in result.persona_comments}
    assert {p.persona_id for p in boundary} <= commented


def test_boundary_can_be_included_explicitly(yeoksam: Panel) -> None:
    evals = [_eval(p, attention=0 if p.is_boundary else 80) for p in yeoksam.personas]
    result = aggregate(yeoksam, evals, ad_id=AD_ID, include_boundary_in_scores=True)
    assert result.scores["attention"] < 80.0
    assert result.boundary_excluded_ids == []


def test_boundary_resistance_still_counted(yeoksam: Panel) -> None:
    """경계 페르소나는 점수에서 빠지지만 저항 요인에는 기여한다 — 존재 이유."""
    evals = [
        _eval(p, resistance="relevance" if p.is_boundary else "none") for p in yeoksam.personas
    ]
    result = aggregate(yeoksam, evals, ad_id=AD_ID)
    assert result.top_resistance == ["relevance"]


def test_weights_renormalized_after_exclusion(yeoksam: Panel) -> None:
    evals = _all_valid(yeoksam, attention=50)
    evals[0] = _eval(
        yeoksam.personas[0],
        attention=50,
        evidence=[FeatureRef(path="age_share.99", value=0.5)],
    )
    result = aggregate(yeoksam, evals, ad_id=AD_ID)
    assert result.excluded_cnt == 1
    assert result.excluded_ids == [yeoksam.personas[0].persona_id]
    assert result.scores["attention"] == 50.0


def test_unknown_persona_id_excluded(yeoksam: Panel) -> None:
    evals = _all_valid(yeoksam)
    evals.append(
        PersonaEval(
            persona_id="ghost",
            attention=100,
            message=100,
            intent=100,
            resistance="none",
            comment="유령",
            evidence=[FeatureRef(path="avg_ticket", value=9546)],
        )
    )
    result = aggregate(yeoksam, evals, ad_id=AD_ID)
    assert "ghost" in result.excluded_ids


def test_high_variance_marks_low_confidence(yeoksam: Panel) -> None:
    evals = [_eval(p, attention=100 if i % 2 else 0) for i, p in enumerate(yeoksam.personas)]
    result = aggregate(yeoksam, evals, ad_id=AD_ID)
    assert result.confidence == "low"
    assert result.max_metric_std > 20.0
    assert any("갈림" in r for r in result.confidence_reasons)


def test_sigma_max_is_configurable(yeoksam: Panel) -> None:
    evals = [_eval(p, attention=100 if i % 2 else 0) for i, p in enumerate(yeoksam.personas)]
    assert aggregate(yeoksam, evals, ad_id=AD_ID, sigma_max=99.0).confidence == "ok"


def test_fallback_forces_low_confidence(yeoksam: Panel) -> None:
    """서울 평균으로 폴백한 평가는 분산과 무관하게 신뢰도가 낮다."""
    panel = yeoksam.model_copy(deep=True)
    panel.features.is_fallback = True
    result = aggregate(panel, _all_valid(panel, attention=70), ad_id=AD_ID)
    assert result.confidence == "low"
    assert result.is_fallback is True
    assert any("서울 평균" in r for r in result.confidence_reasons)


def test_low_demo_coverage_forces_low_confidence(yeoksam: Panel) -> None:
    """미상 매출이 많으면 인구 구성을 믿기 어렵다 (06 §4.4②)."""
    panel = yeoksam.model_copy(deep=True)
    panel.features.demo_coverage = 0.3
    result = aggregate(panel, _all_valid(panel, attention=70), ad_id=AD_ID)
    assert result.confidence == "low"
    assert any("미상 매출" in r for r in result.confidence_reasons)


def test_multiple_confidence_reasons_accumulate(yeoksam: Panel) -> None:
    panel = yeoksam.model_copy(deep=True)
    panel.features.is_fallback = True
    panel.features.demo_coverage = 0.2
    evals = [_eval(p, attention=100 if i % 2 else 0) for i, p in enumerate(panel.personas)]
    result = aggregate(panel, evals, ad_id=AD_ID)
    assert len(result.confidence_reasons) == 3


def test_all_excluded_raises(yeoksam: Panel) -> None:
    bad = [FeatureRef(path="age_share.99", value=0.1)]
    evals = [_eval(p, evidence=bad) for p in yeoksam.personas]
    with pytest.raises(AggregationError, match="집계할 응답이 없습니다"):
        aggregate(yeoksam, evals, ad_id=AD_ID)


def test_comments_sorted_by_weight(yeoksam: Panel) -> None:
    result = aggregate(yeoksam, _all_valid(yeoksam), ad_id=AD_ID)
    weights = [c.weight for c in result.persona_comments]
    assert weights == sorted(weights, reverse=True)


def test_top_resistance_limited_and_ordered(yeoksam: Panel) -> None:
    labels = ["price", "price", "price", "message", "message", "visual"]
    evals = [
        _eval(p, resistance=labels[i] if i < len(labels) else "none")
        for i, p in enumerate(yeoksam.personas)
    ]
    result = aggregate(yeoksam, evals, ad_id=AD_ID)
    assert len(result.top_resistance) <= 3
    assert result.top_resistance[0] == "price"


def test_category_fallback_is_surfaced_but_not_low_confidence(yeoksam: Panel) -> None:
    """업종 폴백은 정밀도만 떨어뜨린다 — '우리 동네' 그라운딩은 유지된다 (07 §4.5).

    화면이 "이 동네 전체 손님 기준" 배지를 띄울 수 있게 결과에 싣되,
    신뢰도를 낮추지는 않는다.
    """
    panel = yeoksam.model_copy(deep=True)
    panel.features.category_cds = []
    panel.features.is_category_fallback = True

    result = aggregate(panel, _all_valid(panel, attention=70), ad_id=AD_ID)
    assert result.is_category_fallback is True
    assert result.confidence == "ok"
    assert result.confidence_reasons == []
