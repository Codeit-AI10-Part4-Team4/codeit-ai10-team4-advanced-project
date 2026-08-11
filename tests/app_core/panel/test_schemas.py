"""스키마 계약 테스트 — A가 넘겨주는 형식이 깨지면 여기서 잡힌다."""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from pydantic import ValidationError

from app_core.panel.schemas import (
    DEMO_COVERAGE_MIN,
    METRIC_FIELDS,
    OPTIONAL_SHARE_FIELDS,
    SHARE_FIELDS,
    FeatureRef,
    Panel,
    PersonaEval,
)

_DEMO = re.compile(r"(\d+)대\s*(남성|여성)")


def _split_demo(demo: str) -> tuple[str, str]:
    """'30대 여성' → ('F', '30')."""
    m = _DEMO.fullmatch(demo.strip())
    assert m, f"demo 형식이 예상과 다릅니다: {demo}"
    age, gender = m.groups()
    return ("M" if gender == "남성" else "F"), age


def test_golden_fixture_parses(yeoksam: Panel) -> None:
    f = yeoksam.features
    assert f.area_nm == "역삼역"
    assert f.category_nm == "커피-음료"
    assert f.quarter == "20261"
    assert len(yeoksam.personas) == 12


def test_all_shares_sum_to_one(yeoksam: Panel) -> None:
    for name in SHARE_FIELDS:
        share: dict[str, float] = getattr(yeoksam.features, name)
        assert sum(share.values()) == pytest.approx(1.0, abs=1e-9), name
    assert sum(p.weight for p in yeoksam.personas) == pytest.approx(1.0, abs=1e-9)


def test_weight_is_product_of_two_axes(yeoksam: Panel) -> None:
    """가중치가 `gender_share × age_share` 곱이어야 한다.

    원본에 성별·연령 교차 데이터가 없어 두 축을 독립으로 곱한다(06 §4.4①).
    이 관계가 깨지면 가중 평균이 상권 구성을 반영하지 못한다.
    """
    f = yeoksam.features
    actual: dict[tuple[str, str], float] = {}
    for persona in yeoksam.personas:
        key = _split_demo(persona.demo)
        actual[key] = actual.get(key, 0.0) + persona.weight

    for (gender, age), weight in actual.items():
        expected = f.gender_share[gender] * f.age_share[age]
        assert weight == pytest.approx(expected, abs=2e-3), f"{gender}{age}"


def test_evidence_cites_both_axes_separately(yeoksam: Panel) -> None:
    """근거는 곱한 값이 아니라 원본 두 값을 각각 인용해야 한다 (06 §4.4①)."""
    non_boundary = [p for p in yeoksam.personas if not p.is_boundary]
    for persona in non_boundary:
        paths = {ref.path.split(".", 1)[0] for ref in persona.evidence}
        assert "gender_share" in paths or "age_share" in paths, persona.persona_id


def test_boundary_personas_use_foot_traffic_evidence(yeoksam: Panel) -> None:
    """경계 페르소나는 '지나다니지만 사지 않는 층'이라 유동인구가 근거다 (06 §7.1)."""
    boundary = [p for p in yeoksam.personas if p.is_boundary]
    assert boundary, "경계 페르소나가 최소 1명은 있어야 한다"

    f = yeoksam.features
    for persona in boundary:
        foot_paths = [r for r in persona.evidence if r.path.startswith("foot_age_share.")]
        assert foot_paths, persona.persona_id
        age = foot_paths[0].path.split(".", 1)[1]
        assert f.foot_age_share[age] > f.age_share[age], (
            f"{age}대는 유동({f.foot_age_share[age]}) > 매출({f.age_share[age]})이어야 한다"
        )


def test_time_axis_matches_weekend_rule(yeoksam: Panel) -> None:
    """`weekend` 유형은 `weekend_ratio > 0.4`일 때만 나온다 (06 §7.1).

    역삼역은 0.138이므로 나오면 안 된다. 이전 픽스처에서 어긋났던 부분이다.
    """
    used = {p.axes.time for p in yeoksam.personas}
    assert len(used) >= 3  # 시간 축이 한 값으로 쏠리지 않는다
    if yeoksam.features.weekend_ratio <= 0.4:
        assert "weekend" not in used


def test_demo_coverage(yeoksam: Panel) -> None:
    f = yeoksam.features
    assert 0.0 < f.demo_coverage <= 1.0
    assert f.low_coverage is (f.demo_coverage < DEMO_COVERAGE_MIN)
    assert f.low_coverage is False  # 역삼역 0.714


def test_avg_ticket_pct_is_a_ratio(yeoksam: Panel) -> None:
    assert 0.0 <= yeoksam.features.avg_ticket_pct <= 1.0


def test_fallback_defaults(yeoksam: Panel) -> None:
    """주소 매칭에 성공했고, 얼마나 가까운 상권에 붙었는지 거리가 실려 온다."""
    assert yeoksam.features.is_fallback is False
    assert yeoksam.features.match_distance_m is not None
    assert 0 <= yeoksam.features.match_distance_m < 500


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


@pytest.mark.parametrize("field", SHARE_FIELDS)
def test_share_sum_mismatch_rejected(yeoksam_raw: dict[str, Any], field: str) -> None:
    data = copy.deepcopy(yeoksam_raw)
    key = next(iter(data["features"][field]))
    data["features"][field][key] += 0.5
    with pytest.raises(ValidationError, match="비중 합"):
        Panel.model_validate(data)


def test_unknown_time_axis_rejected(yeoksam_raw: dict[str, Any]) -> None:
    data = copy.deepcopy(yeoksam_raw)
    data["personas"][0]["axes"]["time"] = "late_night"
    with pytest.raises(ValidationError):
        Panel.model_validate(data)


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
        evidence=[{"path": "avg_ticket", "value": 9546}],  # type: ignore[list-item]
    )
    assert set(ev.metrics()) == set(METRIC_FIELDS)


def test_category_codes_are_a_list(yeoksam: Panel) -> None:
    """07 §4.5 — 서울시 코드를 여러 개 합쳐 읽는다. `fitness`는 4개."""
    f = yeoksam.features
    assert f.category_cds == ["CS100010"]
    assert f.category_nm == "커피-음료"
    assert f.is_category_fallback is False


def test_category_fallback_has_empty_codes(yeoksam_raw: dict[str, Any]) -> None:
    """업종 데이터가 없으면 상권 전체 평균으로 폴백한다 (07 §4.5).

    `photostudio`·`other`처럼 서울시 코드가 없는 업종, 또는 매핑은 되지만
    그 상권에 해당 업종 데이터가 없는 경우다. 에러가 아니라 폴백이다.
    """
    data = copy.deepcopy(yeoksam_raw)
    data["features"].pop("category_cd", None)
    data["features"]["category_cds"] = []
    data["features"]["category_nm"] = "상권 전체"
    data["features"]["is_category_fallback"] = True

    panel = Panel.model_validate(data)
    assert panel.features.category_cds == []
    assert panel.features.is_category_fallback is True


def test_backyard_is_optional(yeoksam: Panel) -> None:
    """배후지는 골목상권에만 있다. 역삼역은 발달상권이라 None (07 §4.4)."""
    f = yeoksam.features
    assert f.area_type == "발달상권"
    assert f.back_age_share is None
    assert f.has_backyard is False


def test_backyard_shares_must_sum_to_one_when_present(
    yeoksam_raw: dict[str, Any],
) -> None:
    data = copy.deepcopy(yeoksam_raw)
    data["features"]["back_age_share"] = {"20": 0.4, "30": 0.6}
    panel = Panel.model_validate(data)
    assert panel.features.has_backyard is True

    data["features"]["back_age_share"] = {"20": 0.4, "30": 0.9}
    with pytest.raises(ValidationError, match="비중 합"):
        Panel.model_validate(data)


@pytest.mark.parametrize("field", OPTIONAL_SHARE_FIELDS)
def test_optional_share_defaults_to_none(yeoksam_raw: dict[str, Any], field: str) -> None:
    """A쪽이 아직 안 채워도 파싱은 된다."""
    data = copy.deepcopy(yeoksam_raw)
    data["features"].pop(field, None)
    assert getattr(Panel.model_validate(data).features, field) is None


def test_population_fields_are_carried(yeoksam: Panel) -> None:
    """상권 성격을 추론이 아니라 실측으로 판정하려면 이 값들이 살아 있어야 한다.

    07 §7.1이 `motive`를 `work_ratio >= 0.7`로 바꿨다. 스키마에 없으면
    Pydantic이 조용히 버려서 평가 프롬프트에 넣을 수가 없다.
    """
    f = yeoksam.features
    assert f.worker_pop == 84399
    assert f.resident_pop == 5764
    assert f.work_ratio == pytest.approx(0.936)
    assert f.household_cnt == 4404
    assert f.apt_cnt == 82
    assert f.apt_avg_price == 326468462


def test_population_fields_have_safe_defaults(yeoksam_raw: dict[str, Any]) -> None:
    data = copy.deepcopy(yeoksam_raw)
    for field in (
        "worker_pop",
        "resident_pop",
        "work_ratio",
        "household_cnt",
        "apt_cnt",
        "apt_avg_price",
    ):
        data["features"].pop(field, None)
    f = Panel.model_validate(data).features
    assert (f.worker_pop, f.resident_pop, f.household_cnt, f.apt_cnt) == (0, 0, 0, 0)
    assert f.work_ratio is None
    assert f.apt_avg_price is None


# --- 불량 수치 방어 (2026-08-11 자체 공격에서 발견) ---------------------------


def test_nan_share_is_rejected(yeoksam_raw: dict[str, Any]) -> None:
    """NaN 은 모든 비교가 거짓이라 합계 검사(`abs(sum-1) > tol`)를 **통과한다.**

    막지 않으면 가중 평균 전체가 NaN 으로 오염되고, 터지는 지점은 입력에서
    한참 멀어서 찾기 어렵다. 실제로 뚫리는 것을 확인하고 막았다.
    """
    data = copy.deepcopy(yeoksam_raw)
    data["features"]["gender_share"] = {"M": float("nan"), "F": 0.5}
    with pytest.raises(ValidationError, match="유한한 수"):
        Panel.model_validate(data)


def test_negative_share_cannot_hide_in_valid_sum(yeoksam_raw: dict[str, Any]) -> None:
    """{-0.5, 1.5} 는 합이 정확히 1이라 합계 검사만으로는 못 잡는다."""
    data = copy.deepcopy(yeoksam_raw)
    data["features"]["gender_share"] = {"M": -0.5, "F": 1.5}
    with pytest.raises(ValidationError, match="유한한 수"):
        Panel.model_validate(data)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), 1.5, -0.001])
def test_out_of_range_share_value_rejected(yeoksam_raw: dict[str, Any], bad: float) -> None:
    data = copy.deepcopy(yeoksam_raw)
    data["features"]["age_share"]["30"] = bad
    with pytest.raises(ValidationError):
        Panel.model_validate(data)


def test_optional_share_also_validates_values(yeoksam_raw: dict[str, Any]) -> None:
    """배후지 비중도 있을 때는 같은 기준으로 검증한다."""
    data = copy.deepcopy(yeoksam_raw)
    data["features"]["back_age_share"] = {"20": float("nan"), "30": 0.5}
    with pytest.raises(ValidationError, match="유한한 수"):
        Panel.model_validate(data)


def test_feature_ref_rejects_non_finite() -> None:
    """NaN 근거는 대조가 조용히 항상 실패한다 — 입구에서 끊는다."""
    with pytest.raises(ValidationError, match="유한한 수"):
        FeatureRef(path="age_share.30", value=float("nan"))


def test_persona_eval_comment_hard_cap() -> None:
    """폭주 코멘트의 마지막 방벽. `_parse` 절단(300)이 먼저, 이 400 이 최후다."""
    with pytest.raises(ValidationError):
        PersonaEval(
            persona_id="p01",
            attention=1,
            message=1,
            intent=1,
            resistance="none",
            comment="가" * 401,
            evidence=[{"path": "avg_ticket", "value": 9546}],  # type: ignore[list-item]
        )
