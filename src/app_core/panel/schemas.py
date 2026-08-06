"""패널 평가 도메인 스키마.

A(데이터·패널 구성) → B(평가·집계) 사이의 계약이다.
`Panel`이 A가 넘겨주는 산출물의 전체 형태이고, 나머지는 B의 산출물이다.

설계 원칙: 정량(세그먼트·가중치·집계·검증)은 결정적 코드가 담당하고
LLM은 서사(narrative)와 평가(PersonaEval)만 만든다. 그래서 이 파일의
검증기들은 LLM 출력을 신뢰하지 않는 전제로 쓰여 있다.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

PriceSens = Literal["low", "mid", "high"]
Motive = Literal["habitual", "exploratory"]
TimeContext = Literal["morning", "weekday_lunch", "afternoon", "evening", "weekend"]
Resistance = Literal["price", "message", "visual", "relevance", "none"]
Confidence = Literal["ok", "low"]

#: 비중 합이 1.0에서 벗어나도 되는 허용치. 반올림 오차만 흡수한다.
SHARE_SUM_TOL: Final = 0.02

#: 가중 평균을 내는 지표 이름. 결과 `scores`의 키와 같다.
METRIC_FIELDS: Final = ("attention", "message", "intent")


class FeatureRef(BaseModel):
    """LLM이 인용한 상권 피처 한 건.

    `path`는 `TradeAreaFeatures` 기준 dot-path다 (예: `sales_share.M30`).
    실제값과 대조하는 것이 `evidence` 모듈의 일이다.
    """

    model_config = ConfigDict(frozen=True)

    path: str = Field(min_length=1)
    value: float


class TradeAreaFeatures(BaseModel):
    """`build_features(주소, 업종)`의 반환값.

    전 필드가 결정적으로 계산된다 — LLM이 개입하지 않는다.
    """

    area_cd: str
    area_nm: str
    dong_nm: str
    quarter: str
    category: str

    #: 성별·연령 매출 비중. 키는 `M30`, `F20` 형식. 합 = 1
    sales_share: dict[str, float]
    #: 시간대 유동인구 비중. 키는 `11-14` 형식. 합 = 1
    time_traffic: dict[str, float]
    weekend_ratio: float = Field(ge=0.0, le=1.0)
    avg_ticket: int = Field(ge=0)
    competitor_cnt: int = Field(ge=0)

    #: 주소 매칭 실패로 서울 평균을 쓴 경우 True.
    #: 결과 화면에서 "이 상권 기준"과 "서울 평균 기준"을 구분하는 데 쓴다.
    is_fallback: bool = False
    #: 가게 좌표와 매칭된 상권 중심 사이의 거리(m).
    match_distance_m: float | None = Field(default=None, ge=0.0)

    @field_validator("sales_share", "time_traffic")
    @classmethod
    def _sums_to_one(cls, v: dict[str, float], info: ValidationInfo) -> dict[str, float]:
        if not v:
            raise ValueError(f"{info.field_name}가 비어 있습니다")
        total = sum(v.values())
        if abs(total - 1.0) > SHARE_SUM_TOL:
            raise ValueError(f"{info.field_name} 비중 합이 1.0이 아닙니다 (합계 {total:.4f})")
        return v


class PersonaAxes(BaseModel):
    """행동 축. 값은 A 영역의 유도 룰이 결정한다.

    `time`은 stage2 §7.1 초안의 3종에서 5종으로 넓혔다.
    카페 상권에서 오전·오후가 실제로 다른 손님이라 아인님 샘플에
    `morning`·`afternoon`이 이미 나왔기 때문이다.
    """

    model_config = ConfigDict(frozen=True)

    price_sens: PriceSens
    motive: Motive
    time: TimeContext


class Persona(BaseModel):
    """가상 손님 한 명. `narrative`만 LLM이 쓰고 나머지는 코드가 채운다."""

    persona_id: str = Field(min_length=1)
    demo: str = Field(min_length=1)
    axes: PersonaAxes
    weight: float = Field(gt=0.0, le=1.0)
    #: 상권에 존재하나 업종 비타깃인 유형. 점수에는 안 넣고 코멘트만 쓴다.
    is_boundary: bool = False
    narrative: str = Field(min_length=1)
    evidence: list[FeatureRef] = Field(min_length=1)


class Panel(BaseModel):
    """A가 넘겨주는 산출물 전체."""

    features: TradeAreaFeatures
    personas: list[Persona] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_personas(self) -> Panel:
        ids = [p.persona_id for p in self.personas]
        if len(set(ids)) != len(ids):
            raise ValueError("persona_id가 중복되었습니다")
        total = sum(p.weight for p in self.personas)
        if abs(total - 1.0) > SHARE_SUM_TOL:
            raise ValueError(f"persona weight 합이 1.0이 아닙니다 (합계 {total:.4f})")
        return self

    def by_id(self, persona_id: str) -> Persona | None:
        return next((p for p in self.personas if p.persona_id == persona_id), None)


class PersonaEval(BaseModel):
    """페르소나 1명의 평가 응답. LLM이 이 스키마로만 답하도록 강제한다."""

    persona_id: str = Field(min_length=1)
    attention: int = Field(ge=0, le=100)
    message: int = Field(ge=0, le=100)
    intent: int = Field(ge=0, le=100)
    resistance: Resistance
    resistance_detail: str = ""
    comment: str = Field(min_length=1)
    #: 필수. 비어 있으면 스키마 단계에서 탈락한다.
    evidence: list[FeatureRef] = Field(min_length=1)

    def metrics(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in METRIC_FIELDS}


class PersonaComment(BaseModel):
    """결과 화면에 뿌릴 페르소나별 한 줄."""

    persona_id: str
    demo: str
    weight: float
    is_boundary: bool
    resistance: Resistance
    comment: str


class EvaluationResult(BaseModel):
    """집계 산출물. 결과 화면이 이것만 보면 되도록 출처 정보까지 담는다."""

    scores: dict[str, float]
    confidence: Confidence
    #: 지표별 가중 표준편차 중 최댓값. `confidence` 판정 근거.
    max_metric_std: float
    top_resistance: list[str]
    persona_comments: list[PersonaComment]

    #: 근거 대조·스키마에서 탈락해 집계에서 빠진 수 (투명성).
    excluded_cnt: int = 0
    excluded_ids: list[str] = Field(default_factory=list)
    #: 경계 페르소나라서 점수에서만 빠진 수. 코멘트는 남아 있다.
    boundary_excluded_ids: list[str] = Field(default_factory=list)

    #: 출처 — 사장님에게 "무엇을 근거로 한 평가인지" 보여주는 데 쓴다.
    area_nm: str
    quarter: str
    is_fallback: bool
