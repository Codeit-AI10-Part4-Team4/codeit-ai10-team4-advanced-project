"""포스터 기획 부품 — 러프한 주문에서 포스터에 들어갈 내용과 색을 LLM 이 정한다.

사장님은 "8월 31일 오픈해요" 정도만 말한다. 특징 3개·태그라인·이벤트를
직접 쓰게 하면 서비스가 아니라 양식 작성이 된다. 그 빈칸을 여기서 채운다.

색은 자유롭게 고르게 하지 않고 검증된 팔레트 중에서 **고르게** 한다 —
자유롭게 두면 조합이 촌스러워지고, 업종마다 다시 손봐야 한다.
"""

import json

from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

from app_core.palettes import PALETTES


class PosterPlan(BaseModel):
    """포스터 한 장에 들어갈 내용과 색 선택."""

    tagline: str = Field(description="가게를 한 줄로 표현하는 감성 문구")
    badge: str = Field(description="우상단 배지 — 예: GRAND OPEN")
    date_line: str = Field(description="날짜 강조 문구 — 예: 8.31 OPEN")
    features: list[str] = Field(description="특징 3개, 각 '제목|설명' 형식")
    event: str = Field(default="", description="이벤트 문구 (없으면 빈 값)")
    palette: str = Field(description="팔레트 이름")

    @field_validator("palette")
    @classmethod
    def _known_palette(cls, v: str) -> str:
        if v not in PALETTES:
            raise ValueError(f"모르는 팔레트입니다: {v!r}")
        return v


_SYSTEM = """너는 동네 가게 광고 포스터를 기획한다.
사장님이 준 정보는 적다. 부족한 부분은 업종과 상호에서 자연스럽게 추론해 채워라.

**지어내면 안 되는 것 — 사장님이 말한 경우에만 쓴다**
- event : 할인·증정·사은품. 말한 적 없으면 반드시 빈 문자열("")로 둔다.
  말했으면 사장님 표현을 살려 짧게 쓴다 (예: "3월 한 달 할인").
- date_line : 날짜. 말한 적 없으면 빈 문자열("")로 둔다.
  **원문에 없는 연도를 붙이지 마라.** "3월"이라고만 했으면 "3월"로 쓴다.
- 가격·수상·인증·원산지처럼 확인할 수 없는 사실도 넣지 마라.

**추론해도 되는 것**
- tagline : 가게 분위기를 한 줄로. 20자 이내
- badge : 상태를 알리는 아주 짧은 말. **6자 이내** (예: 신규 오픈, 봄 시즌, 신메뉴)
  제품 설명을 넣지 마라.
- features 3개 : 그 업종이면 당연히 기대할 만한 수준으로만.
  **제목과 설명이 같은 말이면 안 된다.** 설명은 제목을 풀어주는 다른 정보여야 한다.

형식 규칙
- 특징은 "제목|설명", 제목 12자·설명 18자 이내
- palette 는 다음 중 하나: retro_green, warm_bakery, fresh_mint, modern_dark, soft_pink
- JSON 만 출력한다.

{"tagline": "...", "badge": "...", "date_line": "...",
 "features": ["제목|설명", "제목|설명", "제목|설명"], "event": "...", "palette": "..."}"""


def plan_poster(
    shop: str,
    industry: str,
    product: str,
    situation: str = "",
    tone: str = "",
    extra: str = "",
    transcript: str = "",
) -> PosterPlan:
    """주문 정보로 포스터 기획안을 만든다.

    transcript(사장님이 한 말 원문)를 함께 넘긴다 — 날짜·이벤트처럼
    지어내면 안 되는 정보가 거기에만 들어 있는 경우가 많다.
    """
    order = (
        f"상호: {shop} / 업종: {industry} / 홍보 대상: {product} / "
        f"상황: {situation} / 느낌: {tone} / 그 밖: {extra}\n"
        f"사장님이 한 말 원문:\n{transcript or '(없음)'}"
    )
    res = OpenAI().chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": order}],
    )
    return PosterPlan(**json.loads(res.choices[0].message.content or "{}"))
