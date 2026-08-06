"""근거 대조 테스트 — LLM이 수치를 창작했을 때 걸러내는지."""

from __future__ import annotations

import pytest

from app_core.panel.evidence import (
    RELATIVE_TOLERANCE,
    check_ref,
    evidence_failures,
    evidence_match,
    resolve,
)
from app_core.panel.schemas import FeatureRef, Panel, TradeAreaFeatures


@pytest.fixture
def features(yeoksam: Panel) -> TradeAreaFeatures:
    return yeoksam.features


def test_every_persona_evidence_is_valid(yeoksam: Panel) -> None:
    """골든 픽스처의 근거 24건이 전부 실제값과 맞아야 한다."""
    for persona in yeoksam.personas:
        assert evidence_match(yeoksam.features, persona.evidence), persona.persona_id


def test_resolve_mapping_field(features: TradeAreaFeatures) -> None:
    resolved = resolve(features, "sales_share.M30")
    assert resolved is not None
    assert resolved.value == pytest.approx(0.22)
    assert resolved.exact is False


def test_resolve_hyphenated_key(features: TradeAreaFeatures) -> None:
    """시간대 키에 하이픈이 있어 dot-path 파싱이 깨지기 쉽다."""
    resolved = resolve(features, "time_traffic.11-14")
    assert resolved is not None
    assert resolved.value == pytest.approx(0.26)


def test_resolve_integer_scalar_requires_exact(features: TradeAreaFeatures) -> None:
    resolved = resolve(features, "avg_ticket")
    assert resolved is not None
    assert resolved.exact is True


def test_resolve_float_scalar(features: TradeAreaFeatures) -> None:
    resolved = resolve(features, "weekend_ratio")
    assert resolved is not None
    assert resolved.exact is False


@pytest.mark.parametrize(
    "path",
    [
        "sales_share.M99",  # 없는 키
        "sales_share",  # 매핑인데 키가 없음
        "avg_ticket.foo",  # 스칼라에 하위 경로
        "area_nm",  # 수치가 아님
        "is_fallback",  # bool 은 수치로 보지 않는다
        "match_distance_m",  # None
        "없는필드",
    ],
)
def test_resolve_returns_none(features: TradeAreaFeatures, path: str) -> None:
    assert resolve(features, path) is None


def test_unknown_path_fails(features: TradeAreaFeatures) -> None:
    failure = check_ref(features, FeatureRef(path="sales_share.M99", value=0.1))
    assert failure is not None
    assert failure.reason == "unknown_path"
    assert failure.actual is None


def test_ratio_within_tolerance_passes(features: TradeAreaFeatures) -> None:
    actual = features.sales_share["M30"]  # 0.22
    cited = actual * (1 + RELATIVE_TOLERANCE * 0.8)
    assert check_ref(features, FeatureRef(path="sales_share.M30", value=cited)) is None


def test_ratio_outside_tolerance_fails(features: TradeAreaFeatures) -> None:
    actual = features.sales_share["M30"]
    cited = actual * (1 + RELATIVE_TOLERANCE * 2)
    failure = check_ref(features, FeatureRef(path="sales_share.M30", value=cited))
    assert failure is not None
    assert failure.reason == "value_mismatch"
    assert failure.actual == pytest.approx(actual)


def test_integer_field_rejects_near_miss(features: TradeAreaFeatures) -> None:
    """객단가는 5% 오차가 아니라 정확 일치를 요구한다."""
    assert check_ref(features, FeatureRef(path="avg_ticket", value=6800)) is None
    failure = check_ref(features, FeatureRef(path="avg_ticket", value=6801))
    assert failure is not None
    assert failure.reason == "value_mismatch"


def test_empty_evidence_is_not_a_match(features: TradeAreaFeatures) -> None:
    assert evidence_match(features, []) is False
    assert evidence_failures(features, []) == []


def test_collects_all_failures(features: TradeAreaFeatures) -> None:
    refs = [
        FeatureRef(path="sales_share.M30", value=0.22),  # 통과
        FeatureRef(path="sales_share.M99", value=0.1),  # unknown
        FeatureRef(path="avg_ticket", value=9999),  # mismatch
    ]
    failures = evidence_failures(features, refs)
    assert [f.reason for f in failures] == ["unknown_path", "value_mismatch"]
