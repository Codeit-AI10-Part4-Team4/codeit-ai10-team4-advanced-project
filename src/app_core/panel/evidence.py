"""LLM이 인용한 피처값을 실제값과 대조한다.

"정량은 코드, LLM은 서사만"이라는 원칙의 집행 지점이다.
LLM이 근거 수치를 창작하면 그 응답은 집계에서 빠진다.

대조 규칙 (stage2 §8):
- 비중·비율 등 실수 필드 → 상대 오차 5% 이내
- 정수 필드(`avg_ticket`, `competitor_cnt`) → 정확 일치
- 존재하지 않는 경로 → 탈락
"""

from __future__ import annotations

from typing import Final, Literal, NamedTuple

from app_core.panel.schemas import FeatureRef, TradeAreaFeatures

#: 실수 필드의 상대 오차 허용치.
RELATIVE_TOLERANCE: Final = 0.05

#: dot-path의 앞부분이 이 값이면 뒤를 매핑 키로 해석한다.
_MAPPING_FIELDS: Final = frozenset({"sales_share", "time_traffic"})

FailureReason = Literal["unknown_path", "value_mismatch"]


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

    >>> # sales_share.M30 → 매핑 조회, avg_ticket → 스칼라 조회
    """
    head, _, rest = path.partition(".")

    if head in _MAPPING_FIELDS:
        if not rest:
            return None
        mapping: dict[str, float] = getattr(features, head)
        if rest not in mapping:
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
    """근거 한 건을 대조한다. 통과하면 None."""
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
