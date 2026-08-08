"""근거 대조 테스트 — LLM이 수치를 창작했을 때 걸러내는지."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app_core.panel.evidence import (
    _NON_CITABLE,
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
    """골든 픽스처의 근거가 전부 실제값과 맞아야 한다."""
    for persona in yeoksam.personas:
        assert evidence_match(yeoksam.features, persona.evidence), persona.persona_id


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("gender_share.M", 0.4933),
        ("age_share.30", 0.3823),
        ("time_share.11-14", 0.4789),
        ("foot_age_share.60", 0.0915),
        ("weekend_ratio", 0.138),
        ("avg_ticket_pct", 0.674),
    ],
)
def test_resolve_returns_actual_value(
    features: TradeAreaFeatures, path: str, expected: float
) -> None:
    resolved = resolve(features, path)
    assert resolved is not None
    assert resolved.value == pytest.approx(expected)
    assert resolved.exact is False


def test_resolve_hyphenated_key(features: TradeAreaFeatures) -> None:
    """시간대 키에 하이픈이 있어 dot-path 파싱이 깨지기 쉽다."""
    resolved = resolve(features, "time_share.06-11")
    assert resolved is not None
    assert resolved.value == pytest.approx(0.1608)


@pytest.mark.parametrize("path", ["avg_ticket", "competitor_cnt"])
def test_integer_scalars_require_exact(features: TradeAreaFeatures, path: str) -> None:
    resolved = resolve(features, path)
    assert resolved is not None
    assert resolved.exact is True


@pytest.mark.parametrize(
    "path",
    [
        "age_share.99",  # 없는 키
        "gender_share",  # 매핑인데 키가 없음
        "avg_ticket.foo",  # 스칼라에 하위 경로
        "area_nm",  # 수치가 아님
        "category_cd",  # 수치가 아님
        "is_fallback",  # bool 은 수치로 보지 않는다
        # match_distance_m 은 뺐다 — 이제 실측값(49.7)이 들어와 수치로 해석된다.
        # 다만 상권 특성이 아니라 매칭 품질 지표라 페르소나가 인용할 값은 아니다.
        # 인용 금지 목록을 evidence.py 에 둘지 수호님 판단 필요 (아인).
        "sales_share.M30",  # 06 §4.4① 이전의 폐기된 경로
        "time_traffic.11-14",  # 폐기된 경로
        "없는필드",
    ],
)
def test_resolve_returns_none(features: TradeAreaFeatures, path: str) -> None:
    assert resolve(features, path) is None


def test_unknown_path_fails(features: TradeAreaFeatures) -> None:
    failure = check_ref(features, FeatureRef(path="age_share.99", value=0.1))
    assert failure is not None
    assert failure.reason == "unknown_path"
    assert failure.actual is None


def test_legacy_path_is_rejected(features: TradeAreaFeatures) -> None:
    """`sales_share`는 폐기됐다. 옛 프롬프트가 남아 있으면 여기서 탈락한다."""
    failure = check_ref(features, FeatureRef(path="sales_share.F30", value=0.19))
    assert failure is not None
    assert failure.reason == "unknown_path"


def test_ratio_within_tolerance_passes(features: TradeAreaFeatures) -> None:
    actual = features.age_share["30"]
    cited = actual * (1 + RELATIVE_TOLERANCE * 0.8)
    assert check_ref(features, FeatureRef(path="age_share.30", value=cited)) is None


def test_ratio_outside_tolerance_fails(features: TradeAreaFeatures) -> None:
    actual = features.age_share["30"]
    cited = actual * (1 + RELATIVE_TOLERANCE * 2)
    failure = check_ref(features, FeatureRef(path="age_share.30", value=cited))
    assert failure is not None
    assert failure.reason == "value_mismatch"
    assert failure.actual == pytest.approx(actual)


def test_integer_field_rejects_near_miss(features: TradeAreaFeatures) -> None:
    """객단가는 5% 오차가 아니라 정확 일치를 요구한다."""
    assert check_ref(features, FeatureRef(path="avg_ticket", value=9546)) is None
    failure = check_ref(features, FeatureRef(path="avg_ticket", value=9547))
    assert failure is not None
    assert failure.reason == "value_mismatch"


def test_empty_evidence_is_not_a_match(features: TradeAreaFeatures) -> None:
    assert evidence_match(features, []) is False
    assert evidence_failures(features, []) == []


def test_collects_all_failures(features: TradeAreaFeatures) -> None:
    refs = [
        FeatureRef(path="age_share.30", value=0.3823),  # 통과
        FeatureRef(path="age_share.99", value=0.1),  # unknown
        FeatureRef(path="avg_ticket", value=9999),  # mismatch
    ]
    failures = evidence_failures(features, refs)
    assert [f.reason for f in failures] == ["unknown_path", "value_mismatch"]


@pytest.mark.parametrize("path", sorted(_NON_CITABLE))
def test_quality_metrics_are_not_citable(features: TradeAreaFeatures, path: str) -> None:
    """매칭·데이터 품질 지표는 값이 실재해도 근거로 못 쓴다.

    이런 수치로 근거 요건이 충족되면 LLM 이 실제 인구·행동 데이터를 보지 않고도
    검증 게이트를 통과한다. 값이 실제로 채워진 뒤에도 막혀야 한다.
    """
    resolved = resolve(features, path)
    assert resolved is not None, f"{path} 는 실재하는 수치여야 이 테스트가 의미 있다"

    failure = check_ref(features, FeatureRef(path=path, value=resolved.value))
    assert failure is not None
    assert failure.reason == "not_citable"


def test_not_citable_is_distinguished_from_unknown_path(
    features: TradeAreaFeatures,
) -> None:
    """오타(unknown_path)와 정책 위반(not_citable)을 로그에서 구분할 수 있어야 한다."""
    typo = check_ref(features, FeatureRef(path="age_share.99", value=0.1))
    policy = check_ref(features, FeatureRef(path="match_distance_m", value=320.0))
    assert typo is not None and typo.reason == "unknown_path"
    assert policy is not None and policy.reason == "not_citable"


def test_citable_trade_area_fields_still_pass(features: TradeAreaFeatures) -> None:
    """상권 특성은 그대로 인용 가능해야 한다 — 금지 목록이 과하게 넓어지면 잡힌다."""
    for path in ("weekend_ratio", "avg_ticket_pct", "competitor_cnt", "avg_ticket"):
        resolved = resolve(features, path)
        assert resolved is not None, path
        assert check_ref(features, FeatureRef(path=path, value=resolved.value)) is None, path


def test_backyard_path_resolves_when_present(yeoksam_raw: dict[str, Any]) -> None:
    """골목상권이면 `back_age_share.*` 를 근거로 인용할 수 있어야 한다."""
    data = copy.deepcopy(yeoksam_raw)
    data["features"]["back_age_share"] = {"20": 0.4, "30": 0.6}
    features = Panel.model_validate(data).features

    resolved = resolve(features, "back_age_share.30")
    assert resolved is not None
    assert resolved.value == pytest.approx(0.6)
    assert check_ref(features, FeatureRef(path="back_age_share.30", value=0.6)) is None


def test_backyard_path_fails_when_absent(features: TradeAreaFeatures) -> None:
    """배후지가 없는 상권(발달·전통시장·관광특구)에서 인용하면 탈락한다.

    `None` 매핑에 `in` 을 쓰면 TypeError 가 나므로 방어가 필요하다.
    """
    assert features.back_age_share is None
    assert resolve(features, "back_age_share.30") is None
    failure = check_ref(features, FeatureRef(path="back_age_share.30", value=0.6))
    assert failure is not None
    assert failure.reason == "unknown_path"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("worker_pop", 84399),
        ("resident_pop", 5764),
        ("household_cnt", 4404),
        ("apt_cnt", 82),
        ("apt_avg_price", 326468462),
    ],
)
def test_population_fields_are_citable_and_exact(
    features: TradeAreaFeatures, path: str, expected: int
) -> None:
    """상권 성격·소득 지표는 상권 특성이므로 인용 가능하다. 정수라 정확 일치."""
    resolved = resolve(features, path)
    assert resolved is not None
    assert resolved.exact is True
    assert check_ref(features, FeatureRef(path=path, value=expected)) is None
    assert check_ref(features, FeatureRef(path=path, value=expected + 1)) is not None


def test_work_ratio_is_citable(features: TradeAreaFeatures) -> None:
    assert check_ref(features, FeatureRef(path="work_ratio", value=0.936)) is None
