"""패널 평가 도메인 스키마.

A(데이터·패널 구성) → B(평가·집계) 사이의 계약이다.
`Panel`이 A가 넘겨주는 산출물의 전체 형태이고, 나머지는 B의 산출물이다.
정의 근거는 07 기술계획서 §6, 데이터 모양의 근거는 §4.4(CSV 실물 검수).

설계 원칙: 정량(세그먼트·가중치·집계·검증)은 결정적 코드가 담당하고
LLM은 서사(narrative)와 평가(PersonaEval)만 만든다. 그래서 이 파일의
검증기들은 LLM 출력을 신뢰하지 않는 전제로 쓰여 있다.

소유: 이수호 단독 (07 §12). 아인님은 변경 요청.

평가 대상(Store·AdBrief)은 여기서 다시 정의하지 않는다 — `app_core.schema`의
것을 그대로 받는다(07 §5.1). 저쪽 스키마를 복제하면 필드가 바뀔 때마다
두 곳을 고쳐야 한다.
"""

from __future__ import annotations

from typing import Any, Final, Literal

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

#: 미상 매출 비중이 커서 인구 구성을 믿기 어려운 기준선 (07 §4.4②).
#: 요식업·카페 6,573행 기준 평균 0.879, 중앙값 0.918. 0.5 미만은 전체의 1.2%.
DEMO_COVERAGE_MIN: Final = 0.5

#: 합이 1로 정규화되어야 하는 비중 필드.
SHARE_FIELDS: Final = ("gender_share", "age_share", "time_share", "foot_age_share")

#: 가중 평균을 내는 지표 이름. 결과 `scores`의 키와 같다.
METRIC_FIELDS: Final = ("attention", "message", "intent")


class FeatureRef(BaseModel):
    """LLM이 인용한 상권 피처 한 건.

    `path`는 `TradeAreaFeatures` 기준 dot-path다 (예: `age_share.30`).
    실제값과 대조하는 것이 `evidence` 모듈의 일이다.
    """

    model_config = ConfigDict(frozen=True)

    path: str = Field(min_length=1)
    value: float


class TradeAreaFeatures(BaseModel):
    """`build_features(주소, 업종)`의 반환값. 전 필드가 결정적으로 계산된다.

    성별과 연령이 한 축이 아니라 두 축인 이유: 서울시 원본에 성별·연령 **교차
    데이터가 없다**(07 §4.4①). "30대 여성 매출"이라는 값 자체가 존재하지 않아
    두 축을 따로 두고 페르소나에서 곱한다. 그래서 `evidence`도 곱한 값이 아니라
    원본 두 값을 각각 인용해야 근거 대조가 실제 데이터와 1:1로 맞는다.
    """

    area_cd: str
    area_nm: str
    #: 골목 / 발달 / 전통시장 / 관광특구
    area_type: str
    gu_nm: str
    dong_nm: str
    #: "20261" = 2026년 1분기
    quarter: str
    #: 합산한 서울시 업종코드 (07 §4.5). 서울시 분류가 우리 업종보다 잘게
    #: 쪼개져 있어 여러 코드를 합쳐 읽는다 — `fitness`는 4개. 폴백이면 빈 리스트.
    category_cds: list[str] = Field(default_factory=list)
    #: 화면 표시용 — `industries.yaml`의 label
    category_nm: str
    #: 업종 데이터가 없어 상권 전체 평균을 썼는지. True 면 결과 화면에
    #: "이 동네 전체 손님 기준" 배지를 띄운다. 정밀도는 떨어져도
    #: "우리 동네"라는 그라운딩은 유지되므로 신뢰도를 낮추지는 않는다.
    is_category_fallback: bool = False

    #: 성별 매출 비중. {"M": 0.493, "F": 0.507}, 합 = 1 (미상 제외 후 정규화)
    gender_share: dict[str, float]
    #: 연령대 매출 비중. {"20": 0.165, ... "60": 0.081}, 합 = 1
    age_share: dict[str, float]
    #: 정규화 전 성별·연령 합계. 낮을수록 미상 매출이 많아 인구 구성을 믿기 어렵다.
    demo_coverage: float = Field(gt=0.0, le=1.0)

    #: 시간대 **매출** 비중. 유동인구가 아니다 — 지나다니는 사람과 사는 사람이
    #: 다르기 때문이다 (07 §4.4③: 역삼역 유동은 평탄한데 매출은 11-14가 0.479).
    time_share: dict[str, float]
    #: 유동인구 연령 비중. 도달층이며 경계 페르소나의 근거로 쓴다.
    #: `foot_age_share > age_share`인 연령대가 "지나다니지만 사지 않는 층"이다.
    foot_age_share: dict[str, float]

    weekend_ratio: float = Field(ge=0.0, le=1.0)
    #: 객단가(원) = 당월_매출_금액 / 당월_매출_건수
    avg_ticket: int = Field(ge=0)
    #: 서울 동일 업종 내 분위(0~1). 높을수록 그 동네 손님의 가격 저항이 낮다.
    avg_ticket_pct: float = Field(ge=0.0, le=1.0)
    competitor_cnt: int = Field(ge=0)

    #: 07 §6에 없는 추가 필드 — 06 §5의 "동네 데이터 없이 평가함" 배지 요구 때문.
    #: 주소 매칭 실패로 서울 평균을 쓴 경우 True. 기본값이 있어 A쪽 산출을 깨지 않는다.
    is_fallback: bool = False
    #: 가게 좌표와 매칭된 상권 중심 사이의 거리(m).
    match_distance_m: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_category_cd(cls, data: Any) -> Any:
        """구 픽스처의 단수형 `category_cd`를 `category_cds`로 받아준다.

        07 §6이 2026-08-07 `category_cds: list[str]`(코드 합산)로 바뀌었으나
        픽스처가 아직 단수형이다. 픽스처가 갱신되면 이 변환은 지운다.
        """
        if isinstance(data, dict) and "category_cds" not in data:
            legacy = data.get("category_cd")
            if isinstance(legacy, str):
                return {**data, "category_cds": [legacy]}
            if "category_cd" in data:
                return {**data, "category_cds": []}
        return data

    @field_validator(*SHARE_FIELDS)
    @classmethod
    def _sums_to_one(cls, v: dict[str, float], info: ValidationInfo) -> dict[str, float]:
        if not v:
            raise ValueError(f"{info.field_name}가 비어 있습니다")
        total = sum(v.values())
        if abs(total - 1.0) > SHARE_SUM_TOL:
            raise ValueError(f"{info.field_name} 비중 합이 1.0이 아닙니다 (합계 {total:.4f})")
        return v

    @property
    def low_coverage(self) -> bool:
        """미상 매출이 많아 인구 구성을 믿기 어려운 상태 (07 §4.4②)."""
        return self.demo_coverage < DEMO_COVERAGE_MIN


class PersonaAxes(BaseModel):
    """행동 축. 값은 A 영역의 유도 룰(07 §7.1)이 결정한다.

    `time`은 `time_share`(매출) 상위 구간에서 나오며, `weekend`는
    `weekend_ratio > 0.4`일 때만 추가된다. 역삼역은 0.138이라 나오지 않는다.
    """

    model_config = ConfigDict(frozen=True)

    price_sens: PriceSens
    motive: Motive
    time: TimeContext


class Persona(BaseModel):
    """가상 손님 한 명. `narrative`만 LLM이 쓰고 나머지는 코드가 채운다.

    `weight`는 `gender_share × age_share`의 곱이다(독립 가정). 실제 상관을
    무시하므로 정확한 인구수가 아니라 **상대적 비중**으로만 쓴다 (07 §4.4①).
    """

    persona_id: str = Field(min_length=1)
    demo: str = Field(min_length=1)
    axes: PersonaAxes
    weight: float = Field(gt=0.0, le=1.0)
    #: 지나다니지만 사지 않는 층. 점수에는 안 넣고 코멘트·저항 요인만 쓴다.
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
    """결과 화면에 뿌릴 페르소나별 한 줄.

    `PersonaEval`에는 `demo`가 없어 화면에 "30대 여성"을 못 쓴다. 그래서 별도 뷰다.
    """

    persona_id: str
    demo: str
    weight: float
    is_boundary: bool
    resistance: Resistance
    comment: str


class EvaluationResult(BaseModel):
    """집계 산출물. 결과 화면이 이것만 보면 되도록 출처 정보까지 담는다."""

    ad_id: str
    scores: dict[str, float]
    confidence: Confidence
    #: 신뢰도가 낮은 이유. 결과 화면 배지 문구의 근거가 된다.
    confidence_reasons: list[str] = Field(default_factory=list)
    #: 지표별 가중 표준편차 중 최댓값.
    max_metric_std: float
    top_resistance: list[str]
    #: 재생성 입력으로 그대로 전달된다 (07 §7.3). 요약 콜이 채운다.
    suggestions: list[str] = Field(default_factory=list)
    persona_comments: list[PersonaComment]

    #: 근거 대조·스키마에서 탈락해 집계에서 빠진 수 (투명성).
    excluded_cnt: int = 0
    excluded_ids: list[str] = Field(default_factory=list)
    #: 경계 페르소나라서 점수에서만 빠진 수. 코멘트는 남아 있다.
    boundary_excluded_ids: list[str] = Field(default_factory=list)

    #: 출처 — "무엇을 근거로 한 평가인지" 표시용.
    area_nm: str
    quarter: str
    is_fallback: bool
    #: 업종 폴백 여부. 화면에 "이 동네 전체 손님 기준" 배지를 띄우는 근거.
    is_category_fallback: bool = False
    demo_coverage: float
