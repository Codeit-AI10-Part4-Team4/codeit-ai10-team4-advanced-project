"""주문서 스키마.

챗봇(대화)과 주방(생성) 사이의 약속된 형식이다. 정의는 docs/04_넘겨줄_데이터.md.

Pydantic 을 쓰는 이유는 **틀린 값이 여기서 걸리게** 하기 위해서다.
LLM 이 목록에 없는 업종을 지어내도 이 단계에서 막힌다.

정보가 들어오는 경로는 둘이고, 채우는 자리가 다르다.
  정보 등록  주소·업종·상호·연락처   한 번 입력하고 재사용   → StoreProfile
  대화(NLU)  상품·규격·톤·가격·사진  만들 때마다             → AdBrief 나머지
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app_core import registry

Goal = Literal["copy", "image"]
Mode = Literal["preserve", "scene"]


def _ids(items: list[dict]) -> set[str]:
    return {i["id"] for i in items}


class PriceItem(BaseModel):
    """가격·조건 한 줄.

    ⚠️ AI 가 만들지 않는다. 사장님이 입력한 값만 들어간다.
       없는 가격을 지어내면 표시광고법 위반이다.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="항목명 — 예: 크로플")
    price: str = Field(min_length=1, description="가격·조건 — 예: 4,500원")


class Evaluation(BaseModel):
    """이전 시안의 평가 결과. 재생성할 때 프롬프트에 주입된다."""

    model_config = ConfigDict(extra="forbid")

    top_resistance: list[str] = Field(default_factory=list, description="주 저항 요인")
    suggestions: list[str] = Field(default_factory=list, description="개선 제안")


class StoreProfile(BaseModel):
    """가게 정보 — 정보 등록에서 받는다. 매번 같으므로 저장해두고 재사용한다.

    판단 기준: "매번 똑같고, 결과물이나 평가에 실제로 쓰이는가"
    이 기준을 못 넘으면 넣지 않는다. 사장님의 나이·성별 등은 받지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    industry: str = Field(description="industries.yaml 의 id — 예: cafe")
    address: str = Field(min_length=2, description="주소. 상권 조회 → AI 페르소나의 출발점")
    name: str | None = Field(default=None, description="상호")
    phone: str | None = Field(default=None, description="전단지·POP 에 필요")

    @field_validator("industry")
    @classmethod
    def _known_industry(cls, v: str) -> str:
        if v not in _ids(registry.industries()):
            raise ValueError(f"모르는 업종입니다: {v!r}")
        return v

    @field_validator("address")
    @classmethod
    def _seoul_only(cls, v: str) -> str:
        # 상권 데이터가 서울 기준이라 서울 외 주소는 매칭되지 않는다.
        # 여기서 막지 않으면 한참 뒤 상권 조회에서 실패한다.
        v = v.strip()
        if not v.startswith("서울"):
            raise ValueError("지금은 서울 주소만 지원합니다")
        return v


class AdBrief(BaseModel):
    """주문서 — 생성에 필요한 모든 것.

    필수 항목이 다 차야 생성이 가능하다.
    새 항목은 항상 선택으로 추가한다 — 받는 쪽이 모르면 무시하면 되므로.
    """

    model_config = ConfigDict(extra="forbid")

    # ── 식별 ─────────────────────────────────────────────
    session_id: str = Field(min_length=1, description="로그인 없이 세션 쿠키로 식별")
    ad_id: str = Field(min_length=1, description="어느 시안인지")

    # ── 정보 등록에서 ────────────────────────────────────
    store: StoreProfile

    # ── 대화에서 ─────────────────────────────────────────
    goal: Goal
    format: str = Field(description="formats.yaml 의 id")
    style: str = Field(description="styles.yaml 의 id")
    product: str = Field(min_length=1, description="홍보 대상")

    items: list[PriceItem] = Field(default_factory=list)
    request: str = Field(default="", description="자유 요청")
    with_text: bool = Field(default=True, description="이미지에 글자를 얹을지")
    has_photo: bool = Field(default=False, description="제품 사진 유무 → mode 를 가른다")

    # ── 되먹임 ───────────────────────────────────────────
    prev_evaluation: Evaluation | None = None

    # ── 원문 ─────────────────────────────────────────────
    raw_utterance: str = Field(default="", description="사장님이 한 말 그대로")

    @field_validator("format")
    @classmethod
    def _known_format(cls, v: str) -> str:
        if v not in _ids(registry.formats()):
            raise ValueError(f"모르는 규격입니다: {v!r}")
        return v

    @field_validator("style")
    @classmethod
    def _known_style(cls, v: str) -> str:
        if v not in _ids(registry.styles()):
            raise ValueError(f"모르는 스타일입니다: {v!r}")
        return v

    # ── 계산되는 값 ──────────────────────────────────────
    # 받는 쪽이 각자 계산하면 값이 어긋난다. 넘기는 쪽에서 만들어 함께 보낸다.

    @property
    def mode(self) -> Mode:
        """사진을 올렸는지로 자동 결정. 사용자는 모드를 고르지 않는다."""
        return "preserve" if self.has_photo else "scene"

    @property
    def legal_tags(self) -> list[str]:
        """업종 태그 ∪ 규격 태그. 적용 법령 판별에 쓴다."""
        industry = registry.by_id(registry.industries(), self.store.industry)
        fmt = registry.by_id(registry.formats(), self.format)
        return sorted(registry.legal_tags_for(industry, fmt))

    def to_payload(self) -> dict:
        """다른 담당에게 넘기는 형태 — 계산값을 펼쳐서 함께 보낸다."""
        return {
            **self.model_dump(mode="json"),
            "mode": self.mode,
            "legal_tags": self.legal_tags,
        }
