"""주문서 스키마.

챗봇(대화)과 주방(생성) 사이의 약속된 형식이다. 정의는 docs/04_넘겨줄_데이터.md.

Pydantic 을 쓰는 이유는 **틀린 값이 여기서 걸리게** 하기 위해서다.
LLM 이 목록에 없는 업종을 지어내도 이 단계에서 막힌다.
Ai페르소나 관련 데이터는 현재 서울로 주소가 시작하는지만 검사한다.

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


# NLU가 한 번에 다 못 채운다. 대화가 몇 턴 걸리는 게 정상이라
# AdBrief(다 차야 유효)와 달리 전부 선택으로 둔 초안 모델을 따로 둔다.
REQUIRED_SLOTS = ("goal", "style", "product")


class AdBriefDraft(BaseModel):
    """대화 중 채워지는 값 — LLM이 이번 턴에 뽑아낸 것을 담는다.

    format 은 물어보지 않는다. 지금 규격이 하나뿐이라 고를 게 없다
    (formats.yaml 이 늘어나면 그때 필수 슬롯으로 옮긴다).
    """

    model_config = ConfigDict(extra="forbid")

    goal: Goal | None = None
    style: str | None = None
    # min_length 를 안 건다 — LLM 이 "이번 턴엔 못 찾았다"는 뜻으로 "" 를 돌려줄 수 있고,
    # merge() 가 그 "" 를 걸러내는 역할을 한다. 진짜 값 검증은 AdBrief 승격 때 한다.
    product: str | None = None

    items: list[PriceItem] = Field(default_factory=list)
    request: str = ""
    with_text: bool = True
    has_photo: bool = False
    raw_utterance: str = ""

    @field_validator("style")
    @classmethod
    def _known_style(cls, v: str | None) -> str | None:
        if v is not None and v not in _ids(registry.styles()):
            raise ValueError(f"모르는 스타일입니다: {v!r}")
        return v

    def missing(self) -> list[str]:
        """아직 안 찬 필수 슬롯 이름. 되묻기가 이 목록을 보고 질문을 고른다."""
        return [slot for slot in REQUIRED_SLOTS if getattr(self, slot) is None]

    def merge(self, extracted: AdBriefDraft) -> AdBriefDraft:
        """이번 턴에 새로 뽑아낸 값으로 갱신한다.

        이미 채운 슬롯은 이번 턴에 언급 안 됐으면 그대로 둔다 —
        "아까 카페라고 했잖아"를 매번 다시 말하게 하지 않으려고.
        """
        data = self.model_dump()
        for field, value in extracted.model_dump(exclude_unset=True).items():
            if value not in (None, "", []):
                data[field] = value
        return AdBriefDraft(**data)

    def to_brief(self, *, session_id: str, ad_id: str, store: StoreProfile) -> AdBrief:
        """필수 슬롯이 다 찼을 때만 완성된 주문서로 승격한다."""
        if missing := self.missing():
            raise ValueError(f"아직 안 찬 항목이 있습니다: {missing}")
        (default_format,) = registry.formats()  # 규격이 하나뿐이라 자동 선택
        return AdBrief(
            session_id=session_id,
            ad_id=ad_id,
            store=store,
            goal=self.goal,  # type: ignore[arg-type]  # missing() 이 None 아님을 보장
            format=default_format["id"],
            style=self.style,  # type: ignore[arg-type]
            product=self.product,  # type: ignore[arg-type]
            items=self.items,
            request=self.request,
            with_text=self.with_text,
            has_photo=self.has_photo,
            raw_utterance=self.raw_utterance,
        )
