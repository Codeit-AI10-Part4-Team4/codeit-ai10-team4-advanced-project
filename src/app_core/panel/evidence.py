"""LLM이 인용한 피처값을 실제값과 대조한다.

"정량은 코드, LLM은 서사만"이라는 원칙의 집행 지점이다.
LLM이 근거 수치를 창작하면 그 응답은 집계에서 빠진다.

대조 규칙 (07 §8):
- 비중·비율 등 실수 필드 → 상대 오차 5% 이내
- 정수 필드(`avg_ticket`, `competitor_cnt`) → 정확 일치
- 존재하지 않는 경로 → 탈락
- 인용 금지 필드 → 탈락 (아래 `_NON_CITABLE`)
"""

from __future__ import annotations

from typing import Final, Literal, NamedTuple

from app_core.panel.schemas import MAPPING_FIELDS, FeatureRef, TradeAreaFeatures

#: 실수 필드의 상대 오차 허용치.
RELATIVE_TOLERANCE: Final = 0.05

#: dot-path의 앞부분이 이 값이면 뒤를 매핑 키로 해석한다.
#: 07 §4.4① 이후 성별·연령이 분리됐고, 배후지가 더해져 다섯 개다.
_MAPPING_FIELDS: Final = frozenset(MAPPING_FIELDS)

#: 값은 실재하지만 근거로 인용할 수 없는 필드.
#:
#: 상권 특성이 아니라 **매칭·데이터 품질 지표**다. 페르소나가 "상권 중심에서
#: 320m 떨어져 있어서" 같은 말을 하는 것은 손님의 판단이 아니고, 무엇보다
#: 이런 수치로도 근거 요건이 충족되면 LLM 이 실제 인구·행동 데이터를 보지
#: 않고도 검증 게이트를 통과할 수 있다. 게이트의 목적이 무너진다.
#:
#: `match_distance_m` 은 아인님 지적(2026-08-07), `demo_coverage` 는 같은
#: 이유로 함께 넣었다 — 미상 매출 비중은 데이터 품질이지 손님 특성이 아니다.
#: 둘 다 결과 화면에는 그대로 노출된다(`confidence_reasons` 및 출처 필드).
_NON_CITABLE: Final = frozenset({"match_distance_m", "demo_coverage"})

FailureReason = Literal["unknown_path", "not_citable", "value_mismatch"]


class ResolvedValue(NamedTuple):
    """실제 피처값과, 정확 일치를 요구하는지 여부."""

    value: float
    exact: bool


class EvidenceFailure(NamedTuple):
    """대조 실패 한 건. 로그와 디버깅에 쓴다."""

    path: str
    cited: float
    actual: float | None
    reason: FailureReason


def resolve(features: TradeAreaFeatures, path: str) -> ResolvedValue | None:
    """dot-path로 실제 피처값을 찾는다. 없거나 수치가 아니면 None.

    >>> # age_share.30 → 매핑 조회, avg_ticket → 스칼라 조회
    """
    head, _, rest = path.partition(".")

    if head in _MAPPING_FIELDS:
        if not rest:
            return None
        # 배후지처럼 상권 유형에 따라 None 인 매핑이 있다.
        mapping = getattr(features, head, None)
        if not isinstance(mapping, dict) or rest not in mapping:
            return None
        return ResolvedValue(float(mapping[rest]), exact=False)

    if rest:
        # 스칼라 필드에 하위 경로를 붙인 경우 (예: avg_ticket.foo)
        return None

    raw = getattr(features, head, None)
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return ResolvedValue(float(raw), exact=isinstance(raw, int))


def _within_tolerance(cited: float, actual: float) -> bool:
    if actual == 0.0:
        return cited == 0.0
    return abs(cited - actual) <= RELATIVE_TOLERANCE * abs(actual)


def check_ref(features: TradeAreaFeatures, ref: FeatureRef) -> EvidenceFailure | None:
    """근거 한 건을 대조한다. 통과하면 None.

    `resolve()` 는 "무슨 값인가"만 답하고, 인용해도 되는 값인지는 여기서 본다.
    경로가 실재하므로 `unknown_path` 가 아니라 `not_citable` 로 구분해 남긴다 —
    로그에서 프롬프트 문제와 오타를 헷갈리지 않으려고.
    """
    if ref.path.partition(".")[0] in _NON_CITABLE:
        return EvidenceFailure(ref.path, ref.value, None, "not_citable")

    resolved = resolve(features, ref.path)
    if resolved is None:
        return EvidenceFailure(ref.path, ref.value, None, "unknown_path")

    ok = (
        ref.value == resolved.value
        if resolved.exact
        else _within_tolerance(ref.value, resolved.value)
    )
    if ok:
        return None
    return EvidenceFailure(ref.path, ref.value, resolved.value, "value_mismatch")


def evidence_failures(features: TradeAreaFeatures, refs: list[FeatureRef]) -> list[EvidenceFailure]:
    """실패한 근거를 전부 모아 돌려준다. 빈 리스트면 통과."""
    return [f for ref in refs if (f := check_ref(features, ref)) is not None]


def evidence_match(features: TradeAreaFeatures, refs: list[FeatureRef]) -> bool:
    """근거가 전부 실제값과 맞는지. 근거가 하나도 없으면 실패로 본다."""
    if not refs:
        return False
    return not evidence_failures(features, refs)
