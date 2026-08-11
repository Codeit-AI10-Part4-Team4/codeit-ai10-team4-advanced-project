"""페르소나 평가를 가중 집계한다.

두 종류의 제외가 있고, 성격이 다르다.

1. **탈락** — 근거 대조를 통과 못 한 응답. 점수·저항·코멘트 어디에도 안 쓴다.
   LLM이 수치를 창작한 경우라 신뢰할 수 없기 때문이다.
2. **경계 제외** — `is_boundary` 페르소나. 점수에서만 빼고 저항 요인과
   코멘트에는 남긴다. 07 §7.1의 "점수 기여가 아니라 저항 요인·코멘트
   다양성 목적"이 그 뜻이다.

가중치는 남은 페르소나만으로 재정규화한다.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from math import sqrt
from typing import Final

from app_core.panel.evidence import evidence_failures
from app_core.panel.schemas import (
    DEMO_COVERAGE_MIN,
    METRIC_FIELDS,
    ContrastNote,
    EvaluationResult,
    Panel,
    Persona,
    PersonaComment,
    PersonaEval,
)

logger = logging.getLogger(__name__)

#: 가중 표준편차가 이 값을 넘으면 신뢰도를 낮음으로 본다. 0~100 스케일.
#: 초기값이며 재현성 실험으로 조정할 것.
DEFAULT_SIGMA_MAX: Final = 20.0

#: 결과에 싣는 저항 요인 개수.
TOP_RESISTANCE_N: Final = 3

#: 이 방문 의향을 넘긴 손님의 걸림돌은 세지 않는다.
#:
#: 프롬프트로 세 번 고쳐봤지만(처지에 묶기·임계값·기본값 none) 모델은 계속
#: `price` 를 골랐다 — 동네 평균과 같은 9,500원 광고에도 12명 전원이 그랬다.
#: 광고에 적힌 숫자가 제일 짚기 쉬운 흠이라 그렇다.
#:
#: **그래서 모델에게 부탁하는 대신 코드가 정한다.** 걸림돌은 "발길을 돌린
#: 이유"이므로, 가겠다고 한 손님이 댄 흠은 그 이유가 아니다. 경계 61 은 척도
#: 앵커의 "61~80 한번 가볼까"와 같은 선이다 — 두 곳이 다른 기준을 쓰면
#: 프롬프트와 집계가 어긋난다.
#:
#: 이 규칙은 코멘트를 지우지 않는다. 점수와 코멘트는 그대로 남고, "무엇이
#: 걸리는가"라는 **집계 신호에서만** 뺀다.
RESISTANCE_INTENT_MAX: Final = 60

#: 점수를 낼 최소 인원. 이보다 적으면 가중 평균이 사실상 한두 명의 목소리라
#: 점수는 내되 신뢰도 사유에 남긴다. 탈락이 몰린 날 "12명 패널" 이라는 말이
#: 거짓이 되지 않게 하는 장치다.
MIN_SCORED_PERSONAS: Final = 3

#: 재정규화 후 한 명이 가질 수 있는 비중 상한. 탈락으로 표본이 줄면 남은 한
#: 명이 절반을 넘을 수 있는데, 그 점수는 패널이 아니라 개인의 취향이다.
WEIGHT_CONCENTRATION_MAX: Final = 0.5


class AggregationError(ValueError):
    """집계할 수 있는 응답이 하나도 남지 않았을 때."""


def _weighted_mean(pairs: list[tuple[float, float]]) -> float:
    """(가중치, 값) 쌍의 가중 평균. 가중치 합은 1로 정규화되어 들어온다."""
    return sum(w * x for w, x in pairs)


def _weighted_std(pairs: list[tuple[float, float]], mean: float) -> float:
    return sqrt(sum(w * (x - mean) ** 2 for w, x in pairs))


def aggregate(
    panel: Panel,
    evals: list[PersonaEval],
    *,
    ad_id: str,
    suggestions: list[str] | None = None,
    failed_ids: list[str] | None = None,
    contrast_notes: list[ContrastNote] | None = None,
    extra_reasons: list[str] | None = None,
    elapsed_ms: int = 0,
    sigma_max: float = DEFAULT_SIGMA_MAX,
    include_boundary_in_scores: bool = False,
) -> EvaluationResult:
    """평가 응답을 검증·집계해 결과를 만든다.

    Args:
        panel: A가 넘겨준 패널. 근거 대조의 기준값이 여기 있다.
        evals: 페르소나별 평가 응답. 패널에 없는 `persona_id`는 탈락한다.
        ad_id: 평가 대상 광고물 식별자.
        suggestions: 개선 제안. 집계는 이걸 만들지 않는다 — 별도 요약 콜의
            산출물을 그대로 실어 나른다 (07 §7.3).
        failed_ids: 호출 단계에서 이미 탈락해 `evals` 에 들어오지도 못한
            페르소나. 스키마·근거 재시도까지 실패한 경우다. 여기서 안 받으면
            `excluded_cnt` 가 앞단 실패를 놓쳐 투명성 지표가 거짓이 된다.
        contrast_notes: LLM 없이 만든 대조 문장. 집계는 만들지 않고 실어 나른다.
        extra_reasons: 호출 단계에서 이미 확정된 신뢰도 사유 (예: 시간 초과).
            집계가 아는 사유(폴백·커버리지·분산·표본)와 합쳐진다.
        elapsed_ms: 평가 전체 소요 시간. 결과에 그대로 실린다.
        sigma_max: 이 값을 넘는 가중 표준편차면 `confidence="low"`.
        include_boundary_in_scores: 경계 페르소나를 점수에 넣을지.
            기본값 False가 07 §7.1의 설계다.

    Raises:
        AggregationError: 점수를 낼 응답이 하나도 남지 않은 경우.
    """
    features = panel.features

    valid: list[tuple[Persona, PersonaEval]] = []
    excluded_ids: list[str] = list(failed_ids or [])

    seen_ids: set[str] = set()
    for ev in evals:
        if ev.persona_id in seen_ids:
            # 같은 페르소나의 두 번째 응답. 두 번 세면 그 손님의 가중치가
            # 두 배가 된다 — 상류 버그를 조용히 증폭하느니 버리고 로그로 남긴다.
            logger.debug("중복 응답 무시 %s", ev.persona_id)
            continue
        seen_ids.add(ev.persona_id)
        persona = panel.by_id(ev.persona_id)
        if persona is None or evidence_failures(features, ev.evidence):
            excluded_ids.append(ev.persona_id)
            continue
        valid.append((persona, ev))

    scored = [(p, e) for p, e in valid if include_boundary_in_scores or not p.is_boundary]
    scored_ids = {p.persona_id for p, _ in scored}
    boundary_excluded_ids = [p.persona_id for p, _ in valid if p.persona_id not in scored_ids]

    if not scored:
        raise AggregationError(
            f"집계할 응답이 없습니다 (탈락 {len(excluded_ids)}건, 응답 {len(evals)}건)"
        )

    total_weight = sum(p.weight for p, _ in scored)
    normalized = [(p.weight / total_weight, e) for p, e in scored]

    scores: dict[str, float] = {}
    max_std = 0.0
    for metric in METRIC_FIELDS:
        pairs = [(w, float(getattr(e, metric))) for w, e in normalized]
        mean = _weighted_mean(pairs)
        scores[metric] = round(mean, 1)
        max_std = max(max_std, _weighted_std(pairs, mean))

    # 저항 요인은 경계 페르소나까지 포함해 센다 — 다양성이 이들의 존재 이유다.
    # 다만 가겠다고 한 손님(intent > RESISTANCE_INTENT_MAX)의 흠은 빼고 센다.
    tally: defaultdict[str, float] = defaultdict(float)
    for persona, ev in valid:
        if ev.resistance != "none" and ev.intent <= RESISTANCE_INTENT_MAX:
            tally[ev.resistance] += persona.weight
    ranked = sorted(tally.items(), key=lambda kv: -kv[1])
    top_resistance = [label for label, _ in ranked][:TOP_RESISTANCE_N]
    # 라벨만 주면 "가격이 걸린다"까지만 말할 수 있다. 얼마나 걸리는지를 화면이
    # 쓰려면 크기가 필요하다. 통과분 가중치로 정규화한다(`none` 제외).
    counted = sum(tally.values())
    resistance_share = {label: round(w / counted, 3) for label, w in ranked} if counted else {}

    comments = [
        PersonaComment(
            persona_id=p.persona_id,
            demo=p.demo,
            weight=p.weight,
            is_boundary=p.is_boundary,
            resistance=e.resistance,
            comment=e.comment,
        )
        for p, e in sorted(valid, key=lambda pe: -pe[0].weight)
    ]

    # 신뢰도를 떨어뜨리는 사유는 셋이고 성격이 다르다. 화면 배지 문구가
    # 달라져야 하므로 사유를 따로 남긴다.
    # 업종 폴백(is_category_fallback)은 여기 넣지 않는다 — 정밀도가 낮아질 뿐
    # "우리 동네" 그라운딩은 유지되므로 신뢰 불가가 아니다 (07 §4.5).
    reasons: list[str] = list(extra_reasons or [])
    if len(scored) < MIN_SCORED_PERSONAS:
        reasons.append(
            f"통과한 손님이 {len(scored)}명뿐이라 표본이 작음 (기준 {MIN_SCORED_PERSONAS}명)"
        )
    top_weight = max(w for w, _ in normalized)
    if top_weight > WEIGHT_CONCENTRATION_MAX:
        reasons.append(f"한 손님의 비중이 {top_weight:.0%}라 결과가 그쪽으로 쏠림")
    if features.is_fallback:
        reasons.append("동네 데이터 없이 서울 평균으로 평가함")
    if features.low_coverage:
        reasons.append(
            f"미상 매출이 많아 인구 구성 신뢰도가 낮음 "
            f"(coverage {features.demo_coverage:.3f} < {DEMO_COVERAGE_MIN})"
        )
    if max_std > sigma_max:
        reasons.append(f"손님별 평가가 갈림 (표준편차 {max_std:.1f} > {sigma_max})")

    return EvaluationResult(
        ad_id=ad_id,
        scores=scores,
        confidence="low" if reasons else "ok",
        confidence_reasons=reasons,
        max_metric_std=round(max_std, 2),
        top_resistance=top_resistance,
        resistance_share=resistance_share,
        suggestions=list(suggestions or []),
        contrast_notes=list(contrast_notes or []),
        persona_comments=comments,
        excluded_cnt=len(excluded_ids),
        excluded_ids=excluded_ids,
        boundary_excluded_ids=boundary_excluded_ids,
        area_nm=features.area_nm,
        quarter=features.quarter,
        is_fallback=features.is_fallback,
        is_category_fallback=features.is_category_fallback,
        demo_coverage=features.demo_coverage,
        elapsed_ms=elapsed_ms,
    )
