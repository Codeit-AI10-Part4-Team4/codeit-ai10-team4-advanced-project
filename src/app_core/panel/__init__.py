"""AI 손님 패널 — 평가·집계 (B 영역).

A(데이터·패널 구성)가 만든 `Panel`을 받아 페르소나별 평가를 검증하고
가중 집계해 `EvaluationResult`를 낸다.
"""

from app_core.panel.aggregate import AggregationError, aggregate
from app_core.panel.evaluator import evaluate
from app_core.panel.evidence import (
    EvidenceFailure,
    evidence_failures,
    evidence_match,
    resolve,
)
from app_core.panel.schemas import (
    EvaluationResult,
    FeatureRef,
    Panel,
    Persona,
    PersonaAxes,
    PersonaComment,
    PersonaEval,
    TradeAreaFeatures,
)

__all__ = [
    "AggregationError",
    "EvaluationResult",
    "EvidenceFailure",
    "FeatureRef",
    "Panel",
    "Persona",
    "PersonaAxes",
    "PersonaComment",
    "PersonaEval",
    "TradeAreaFeatures",
    "aggregate",
    "evaluate",
    "evidence_failures",
    "evidence_match",
    "resolve",
]
