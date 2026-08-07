"""주문서 스키마.

챗봇(대화)과 생성(문구·이미지) 사이의 약속된 형식이다.
정의는 docs/05_최종계획서.md.

Pydantic 을 쓰는 이유는 **틀린 값이 여기서 걸리게** 하기 위해서다.
LLM 이 목록에 없는 업종을 지어내도 이 단계에서 막힌다.

정보가 들어오는 경로는 둘이고, 채우는 자리가 다르다.
  가게 등록  업종·주소·상호·연락처   한 번 등록하고 재사용   → StoreInput
  대화       상품·가격·상황·톤       광고 만들 때마다        → AdBrief
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app_core import registry

Goal = Literal["image", "copy"]

# 대화로 반드시 채워야 하는 것. goal 은 고정 버튼으로 이미 정해져서 여기 없다.
REQUIRED_SLOTS = ("product", "price")


class StoreInput(BaseModel):
    """가게 등록 폼. 한 사용자가 여러 개를 가질 수 있다."""

    model_config = ConfigDict(extra="forbid")

    industry: str = Field(description="industries.yaml 의 id — 예: cafe")
    name: str = Field(min_length=1, description="상호")
    address: str = Field(default="서울", min_length=2, description="주소. 상권 조회의 출발점")
    phone: str = Field(default="", description="전단지·POP 에 넣는다")
    industry_note: str = Field(
        default="", description="업종이 other 일 때 사장님이 직접 적은 업종명"
    )

    @field_validator("industry")
    @classmethod
    def _known_industry(cls, v: str) -> str:
        if v not in registry.industry_ids():
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

    @model_validator(mode="after")
    def _other_needs_note(self) -> StoreInput:
        # "기타"로 두고 빈칸으로 넘기면 프롬프트에 업종이 "기타"로 들어가서
        # LLM 이 무슨 가게인지 모른 채 문구를 쓰게 된다.
        if self.industry == registry.OTHER and not self.industry_note.strip():
            raise ValueError("기타를 고르셨으면 업종을 직접 적어주세요")
        return self

    @property
    def industry_label(self) -> str:
        """프롬프트·화면에 쓰는 업종 이름. 기타면 사장님이 적은 값."""
        if self.industry == registry.OTHER:
            return self.industry_note.strip()
        return registry.label_of(self.industry)


class Store(StoreInput):
    """DB 에 저장된 가게 — 등록 폼에 식별자가 붙은 것."""

    id: int
    user_id: int


class AdBrief(BaseModel):
    """주문서 — 생성에 필요한 모든 것. 필수가 다 차야 만들어진다."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    product: str = Field(min_length=1, description="홍보 대상 — 예: 크로플")
    price: int = Field(ge=0, description="원 단위. 0 이면 광고에 가격을 넣지 않는다")

    situation: str = Field(default="", description="신메뉴·할인·오픈 등 알리려는 것")
    tone: str = Field(default="", description="원하는 느낌 — 자유 텍스트")
    extra: str = Field(default="", description="그 밖의 요청")
    with_sub: bool = Field(default=True, description="서브 문구까지 만들지")

    @property
    def show_price(self) -> bool:
        """0 원은 '가격 없음'이라는 뜻이다. 광고에 0원이라고 쓰면 안 된다."""
        return self.price > 0


class AdBriefDraft(BaseModel):
    """대화 중 채워지는 값.

    AdBrief 는 다 차야 유효해서 대화 중간 상태를 못 담는다.
    전부 선택으로 두고, 다 차면 to_brief() 로 승격한다.
    """

    model_config = ConfigDict(extra="forbid")

    goal: Goal | None = None
    product: str | None = None
    # LLM 이 "이번 턴엔 못 찾았다"는 뜻으로 None 을 준다. 0 은 '가격 없음'이라
    # 뜻이 다르므로 둘을 섞으면 안 된다.
    price: int | None = Field(default=None, ge=0)

    situation: str = ""
    tone: str = ""
    extra: str = ""
    with_sub: bool = True

    def missing(self) -> list[str]:
        """아직 안 찬 필수 슬롯. 이게 비면 생성할 수 있다."""
        return [slot for slot in REQUIRED_SLOTS if getattr(self, slot) is None]

    def merge(self, extracted: AdBriefDraft) -> AdBriefDraft:
        """이번 턴에 새로 뽑아낸 값으로 갱신한다.

        이번 턴에 언급 안 된 슬롯은 이전 값을 유지한다 —
        "아까 크로플이라고 했잖아"를 매번 다시 말하게 하지 않으려고.
        """
        data = self.model_dump()
        for field, value in extracted.model_dump(exclude_unset=True).items():
            if value not in (None, ""):
                data[field] = value
        return AdBriefDraft(**data)

    def to_brief(self) -> AdBrief:
        """필수가 다 찼을 때만 주문서로 승격한다."""
        if missing := self.missing():
            raise ValueError(f"아직 안 찬 항목이 있습니다: {missing}")
        return AdBrief(
            goal=self.goal,  # type: ignore[arg-type]  # missing() 이 None 아님을 보장
            product=self.product,  # type: ignore[arg-type]
            price=self.price,  # type: ignore[arg-type]
            situation=self.situation,
            tone=self.tone,
            extra=self.extra,
            with_sub=self.with_sub,
        )


class CopyCandidate(BaseModel):
    """문구 후보 하나.

    헤드라인과 서브를 나눠서 준다 — 이미지에 얹을 때 헤드라인은 크게,
    서브는 작게 배치해야 해서 한 덩어리로 주면 어디서 자를지 알 수 없다.
    """

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    sub: str = ""


class ChatTurn(BaseModel):
    """챗봇 한 턴의 응답. 메시지와 선택지를 함께 낸다."""

    model_config = ConfigDict(extra="forbid")

    message: str
    options: list[str] = Field(default_factory=list, description="힌트일 뿐 — 필수가 아니다")
    draft: AdBriefDraft
