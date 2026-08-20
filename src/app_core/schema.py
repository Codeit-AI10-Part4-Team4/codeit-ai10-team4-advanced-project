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

# 다시 만드는 경로는 셋이지만 담기는 자리는 하나다.
#   typed   사장님이 말로 요청      "좀 더 밝게"
#   option  화면 선택지를 누름       [더 짧게]
#   panel   AI 손님 패널 평가 결과   suggestions[] · top_resistance[]
FeedbackSource = Literal["typed", "option", "panel"]

# 대화로 반드시 채워야 하는 것. goal 은 고정 버튼으로 이미 정해져서 여기 없다.
# 이게 비면 광고를 만들 수 없다.
#
# ⚠️ 목표에 따라 다르다 — 실제 판정은 `AdBriefDraft.required` 를 본다.
REQUIRED_SLOTS = ("product", "price")

# 없어도 만들 수는 있지만, 있으면 사장님 의도에 훨씬 가까워지는 것.
# **한 번씩만 묻고 넘어간다** — 안 그러면 사장님이 답을 피할 때 대화가 맴돈다.
HELPFUL_SLOTS = ("situation", "tone")


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


class CopyCandidate(BaseModel):
    """문구 후보 하나.

    헤드라인과 서브를 나눠서 준다 — 이미지에 얹을 때 헤드라인은 크게,
    서브는 작게 배치해야 해서 한 덩어리로 주면 어디서 자를지 알 수 없다.
    """

    model_config = ConfigDict(extra="forbid")

    id: int | None = None  #: DB 에 저장된 뒤에만 있다 — 생성 직후엔 None, ads.copies_of 가 채운다
    headline: str = Field(min_length=1)
    sub: str = ""


class Feedback(BaseModel):
    """다시 만드는 이유.

    경로는 셋이지만(말로 요청·선택지·패널 평가) 담기는 형태는 하나다.
    받는 쪽에서 경로마다 다르게 처리하지 않아도 되게 하려는 것이다.
    """

    model_config = ConfigDict(extra="forbid")

    source: FeedbackSource
    notes: list[str] = Field(min_length=1, description="고쳐달라는 내용")
    resistance: list[str] = Field(
        default_factory=list, description="패널 평가의 저항 요인. source=panel 일 때만"
    )


class AdBrief(BaseModel):
    """주문서 — 생성에 필요한 모든 것. 필수가 다 차야 만들어진다.

    슬롯과 원문을 **둘 다** 들고 간다. 역할이 다르다.
      슬롯   검증·저장·조건 판단 — 형식이 고정이라 받는 쪽이 믿고 쓴다
      원문   생성 프롬프트에 통째로 넣는다 — 슬롯에 안 담기는 뉘앙스를 살린다
    """

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    product: str = Field(min_length=1, description="홍보 대상 — 예: 크로플")
    price: int = Field(ge=0, description="원 단위. 0 이면 광고에 가격을 넣지 않는다")

    situation: str = Field(default="", description="이 광고를 만드는 이유 — 자유 텍스트")
    tone: str = Field(default="", description="원하는 느낌 — 자유 텍스트")
    extra: str = Field(default="", description="그 밖의 요청")
    with_sub: bool = Field(default=True, description="서브 문구까지 만들지")

    # ── 사진 ────────────────────────────────────────────────
    # 이미지는 JSON 에 실을 수 없어서 사진 보관함(photo_store)에 두고 번호만 싣는다.
    #
    # 칸을 셋으로 나눈 이유: 사진마다 **받는 쪽이 해야 할 일이 다르다.**
    # 한 칸에 몰아넣으면 "이 사진을 살리라는 건지 흉내내라는 건지"를 받는 쪽이
    # 알 수 없다. 나눠두면 각자 자기 칸만 보면 되고, "내 상품은 살리되 분위기는
    # 이 레퍼런스로" 같은 조합도 그냥 된다.
    photo_id: int | None = Field(
        default=None, ge=1, description="제품 사진 — 이 상품을 **그대로 살린다**(누끼)"
    )
    ref_id: int | None = Field(
        default=None, ge=1, description="레퍼런스 — 분위기만 **참고한다**. 상품을 베끼지 않는다"
    )
    sketch_id: int | None = Field(
        default=None, ge=1, description="스케치 — 배치·구도를 **따라간다**"
    )

    # 제품 사진을 비전 모델로 읽은 메모(vision.describe). photo_id 와 짝이다.
    # ⚠️ 사장님이 한 말이 아니다. 그래서 tone·situation 에 섞지 않고 자리를 따로 뒀다.
    photo_note: str = Field(default="", description="제품 사진에서 읽은 생김새·분위기")

    # 슬롯이 못 담는 것을 여기서 건진다.
    # "단골분들이 매콤한 걸 좋아하셔서" 같은 말은 어느 슬롯에도 안 들어가지만
    # 문구를 쓸 때 가장 쓸모 있는 정보다.
    transcript: list[str] = Field(
        default_factory=list, description="사장님이 한 말 그대로, 순서대로"
    )

    # ── 다시 만들 때만 채워진다 ────────────────────────────
    # 처음 만들 때는 둘 다 비어 있다.
    prev_copies: list[CopyCandidate] = Field(
        default_factory=list, description="직전에 만든 문구. 이것과 다르게 만들라고 넣는다"
    )
    feedback: Feedback | None = Field(default=None, description="왜 다시 만드는지")

    @property
    def is_revision(self) -> bool:
        """다시 만드는 중인가. 프롬프트와 저장 양쪽에서 갈린다."""
        return self.feedback is not None

    def revised(self, feedback: Feedback, previous: list[CopyCandidate]) -> AdBrief:
        """재생성용 주문서를 만든다.

        상품·가격 같은 조건은 그대로 두고 피드백과 직전 결과만 얹는다.
        조건까지 바꾸려면 대화로 돌아가야 한다 — 여기서 슬롯을 건드리면
        사장님이 말한 적 없는 값이 조용히 바뀐다.
        """
        return self.model_copy(update={"feedback": feedback, "prev_copies": previous})

    @property
    def show_price(self) -> bool:
        """0 원은 '가격 없음'이라는 뜻이다. 광고에 0원이라고 쓰면 안 된다."""
        return self.price > 0

    @property
    def items(self) -> list[dict[str, str]]:
        """가격 항목 목록 — 품질 검증·이미지 담당에게 넘기는 형태.

        받는 쪽이 [{"name","price"}] 를 기대한다. 우리는 상품 하나·가격 하나를
        받으므로 항목은 최대 한 개다. 0 원이면 가격을 안 넣기로 했으므로 빈 목록.

        슬롯으로 두지 않고 계산해서 만드는 이유: 가격은 정수 하나로 받아야
        "말 안 함(None)"과 "가격 없음(0)"을 구분할 수 있다.
        """
        if not self.show_price:
            return []
        return [{"name": self.product, "price": f"{self.price:,}원"}]

    @property
    def raw_utterance(self) -> str:
        """사장님이 한 말 전체를 한 덩어리로. 프롬프트에 넣을 때 쓴다."""
        return "\n".join(self.transcript)


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
    # 대화로 묻지 않는다. 사장님이 화면에서 사진을 올리면 채워진다.
    photo_id: int | None = Field(default=None, ge=1)
    ref_id: int | None = Field(default=None, ge=1)
    sketch_id: int | None = Field(default=None, ge=1)
    photo_note: str = ""

    transcript: list[str] = Field(default_factory=list, description="사장님이 한 말 그대로")
    asked: list[str] = Field(
        default_factory=list, description="이미 물어본 슬롯. 같은 걸 두 번 묻지 않으려고 센다"
    )

    @property
    def required(self) -> tuple[str, ...]:
        """이 광고에 정말 필요한 슬롯. **목표에 따라 다르다.**

        이미지 광고는 사진으로 분위기만 내는 경우가 많아 가격을 안 묻는다
        (팀 합의 2026-08-13). 문구 광고는 가격이 문구에 그대로 들어가므로 받는다.

        `REQUIRED_SLOTS` 를 직접 읽지 말고 이걸 봐야 한다 — 그 상수는 "문구
        광고 기준"이라 이미지 광고에서는 사장님이 말할 생각도 없는 값을 계속
        묻게 된다.
        """
        if self.goal == "image":
            return tuple(s for s in REQUIRED_SLOTS if s != "price")
        return REQUIRED_SLOTS

    @property
    def optional(self) -> tuple[str, ...]:
        """한 번만 묻고 넘어가는 슬롯. **안 답해도 광고를 만든다.**

        이미지 광고의 가격이 여기로 온다. 필수에서 빼기만 하면 넣고 싶었던
        사장님이 그 생각을 **스스로 해내야** 한다 — 그건 선택 항목이 아니다.
        한 번은 묻되 빠져나갈 길을 준다(`chat.ASK_HELPFUL`).
        """
        if self.goal == "image":
            return ("price", *HELPFUL_SLOTS)
        return HELPFUL_SLOTS

    def _unanswered(self, slot: str) -> bool:
        """아직 답을 못 받았나. 가격의 0 은 빈 값이 아니라 '없음'이라는 **답**이다."""
        value = getattr(self, slot)
        return value is None if slot == "price" else not value

    def missing(self) -> list[str]:
        """아직 안 찬 **필수** 슬롯. 이게 비어야 생성할 수 있다."""
        return [slot for slot in self.required if getattr(self, slot) is None]

    def remaining_slots(self) -> list[str]:
        """아직 물어볼 게 남은 슬롯 전부. 우선순위 순이다.

        필수를 먼저 다 받고, 그 다음 도움되는 것을 한 번씩만 묻는다.
        사장님이 답을 안 해도 asked 에 남아서 다시 묻지 않는다.
        """
        left = [s for s in self.required if getattr(self, s) is None]
        left += [s for s in self.optional if self._unanswered(s) and s not in self.asked]
        return left

    def next_slot(self) -> str | None:
        """다음에 물어볼 것 하나. 더 물을 게 없으면 None."""
        left = self.remaining_slots()
        return left[0] if left else None

    def mark_asked(self, slot: str) -> AdBriefDraft:
        """물어봤다고 표시한다. 답을 받았는지와 무관하게 한 번이면 충분하다."""
        if slot in self.asked:
            return self
        return self.model_copy(update={"asked": [*self.asked, slot]})

    def merge(self, extracted: AdBriefDraft) -> AdBriefDraft:
        """이번 턴에 새로 뽑아낸 값으로 갱신한다.

        이번 턴에 언급 안 된 슬롯은 이전 값을 유지한다 —
        "아까 크로플이라고 했잖아"를 매번 다시 말하게 하지 않으려고.
        """
        data = self.model_dump()
        for field, value in extracted.model_dump(exclude_unset=True).items():
            # transcript·asked 는 덮어쓰지 않는다. 쌓이는 것이지 바뀌는 게 아니다.
            if field not in ("transcript", "asked") and value not in (None, ""):
                data[field] = value
        return AdBriefDraft(**data)

    def with_utterance(self, utterance: str) -> AdBriefDraft:
        """사장님이 한 말을 기록에 덧붙인다. 슬롯에 안 담긴 것도 여기 남는다."""
        said = utterance.strip()
        if not said:
            return self
        return self.model_copy(update={"transcript": [*self.transcript, said]})

    def to_brief(self) -> AdBrief:
        """필수가 다 찼을 때만 주문서로 승격한다."""
        if missing := self.missing():
            raise ValueError(f"아직 안 찬 항목이 있습니다: {missing}")
        return AdBrief(
            goal=self.goal,  # type: ignore[arg-type]  # missing() 이 None 아님을 보장
            product=self.product,  # type: ignore[arg-type]
            # 안 물어본 가격(None)은 '가격 없음'(0)으로 굳힌다. 주문서 단계에서는
            # 둘의 결과가 같다 — 광고에 가격을 안 넣는다. 구분이 필요한 건 대화
            # 중(더 물어볼까)이고 그건 이 클래스의 `price: int | None` 이 한다.
            price=self.price or 0,
            situation=self.situation,
            tone=self.tone,
            extra=self.extra,
            with_sub=self.with_sub,
            photo_id=self.photo_id,
            ref_id=self.ref_id,
            sketch_id=self.sketch_id,
            photo_note=self.photo_note,
            transcript=self.transcript,
        )


class ChatTurn(BaseModel):
    """챗봇 한 턴의 응답. 메시지와 선택지를 함께 낸다."""

    model_config = ConfigDict(extra="forbid")

    message: str
    options: list[str] = Field(default_factory=list, description="힌트일 뿐 — 필수가 아니다")
    draft: AdBriefDraft
