"""포스터 기획 부품 — 러프한 주문에서 포스터에 들어갈 내용과 색을 LLM 이 정한다.

사장님은 "8월 31일 오픈해요" 정도만 말한다. 특징·태그라인을 직접 쓰게 하면 서비스가
아니라 양식 작성이 된다. 그래서 여기서 채우되 — **없는 사실은 지어내지 않는다.**

v1 은 "업종에서 당연히 기대할 만한" 특징을 추론하게 했는데, 그러면 확인한 적 없는
"신선한 재료"·"최고급 원두" 가 광고에 실린다. 광고에서 그건 품질 문제가 아니라
허위 표시 위험이 있다. 근거가 없으면 빈칸으로 두고, 포스터는 빈 항목을 알아서 생략한다
(poster.py 의 `if badge:` · `if event:` 등).

색은 자유롭게 고르게 하지 않고 검증된 팔레트 중에서 **고르게** 한다 —
자유롭게 두면 조합이 촌스러워지고, 업종마다 다시 손봐야 한다.
"""

from pydantic import BaseModel, Field, field_validator

from app_core.llm import ChatClient, get_client
from app_core.palettes import PALETTES


class PosterPlan(BaseModel):
    """포스터 한 장에 들어갈 내용과 색 선택.

    tagline·palette 를 뺀 나머지는 **사장님 말에 근거가 있을 때만** 채운다. 기본은 빈 값이다.
    """

    tagline: str = Field(default="", description="분위기 한 줄 — 사실 주장 금지")
    badge: str = Field(default="", description="우상단 배지 — 근거가 있을 때만")
    date_line: str = Field(default="", description="날짜 — 사장님이 말했을 때만")
    features: list[str] = Field(
        default_factory=list, description="사장님이 말한 특징만 '제목|설명'"
    )
    event: str = Field(default="", description="이벤트 — 사장님이 말했을 때만")
    palette: str = Field(description="팔레트 이름")

    @field_validator("palette")
    @classmethod
    def _known_palette(cls, v: str) -> str:
        if v not in PALETTES:
            raise ValueError(f"모르는 팔레트입니다: {v!r}")
        return v


_SYSTEM = """너는 동네 가게 광고 포스터를 기획한다.

**광고는 사실을 말해야 한다. 사장님이 말하지 않은 것은 쓰지 않는다.**
확인할 수 없는 특징(재료·품질·맛·수상·인증·원산지·인기)은 사실과 다른 광고가 될 수 있으므로 쓰지 않는다.
정보가 없으면 빈칸으로 두는 것이 정답이다 — 빈칸은 포스터에서 그냥 생략된다.

**근거가 있을 때만 쓴다 — 없으면 빈 문자열("") 또는 빈 목록([])**
- event : 할인·증정·사은품. 사장님이 말했을 때만. 표현을 살려 짧게 (예: "3월 한 달 할인")
- date_line : 날짜. 말했을 때만. **원문에 없는 연도를 붙이지 마라** ("3월"이라 했으면 "3월")
- badge : 사장님 말에 근거가 있을 때만. **6자 이내**
  (예: "신메뉴 나왔어요" → "신메뉴" · "다음 주 오픈해요" → "신규 오픈")
- features : **사장님이 말한 특징만** "제목|설명" 형식으로, 최대 3개. 말한 게 없으면 []
  업종에서 당연히 기대할 만한 것을 추론하지 마라 — "신선한 재료", "다양한 토핑",
  "최고급 원두", "정성 가득" 같은 말은 사장님이 그렇게 말한 경우가 아니면 쓰지 않는다

**창작해도 되는 것은 둘뿐이다**
- tagline : 가게 분위기를 한 줄로, 20자 이내.
  단 **사실을 주장하면 안 된다** — 재료·품질·맛·인기·수상은 분위기가 아니라 사실이다
  (O "천천히 머무는 오후" · X "최고의 원두로 내린 커피")
- palette : 아래 다섯 중 하나

형식 규칙
- 특징은 "제목|설명", 제목 12자·설명 18자 이내. 제목과 설명이 같은 말이면 안 된다
- palette 는 다음 중 하나: retro_green, warm_bakery, fresh_mint, modern_dark, soft_pink
- JSON 만 출력한다. 근거가 없는 칸은 아래 예시처럼 비워서 낸다.

{"tagline": "...", "badge": "", "date_line": "",
 "features": [], "event": "", "palette": "..."}"""


def plan_poster(
    shop: str,
    industry: str,
    product: str,
    situation: str = "",
    tone: str = "",
    extra: str = "",
    transcript: str = "",
    client: ChatClient | None = None,
) -> PosterPlan:
    """주문 정보로 포스터 기획안을 만든다.

    transcript(사장님이 한 말 원문)를 함께 넘긴다 — 날짜·이벤트처럼
    지어내면 안 되는 정보가 거기에만 들어 있는 경우가 많다.

    `client` 는 테스트에서 가짜를 끼우는 통로다 (AGENTS.md — 외부 API 호출 테스트는
    mock 을 쓴다). 안 주면 `MODEL_PROFILE` 이 고른 백엔드를 쓴다.
    """
    order = (
        f"상호: {shop} / 업종: {industry} / 홍보 대상: {product} / "
        f"상황: {situation} / 느낌: {tone} / 그 밖: {extra}\n"
        f"사장님이 한 말 원문:\n{transcript or '(없음)'}"
    )

    raw = (client or get_client()).complete_json(_SYSTEM, order)
    if not raw:
        # stub 프로필이거나 빈 응답. 그냥 넘기면 pydantic 이 "필드 5개 없음"으로
        # 터져서 화면에서는 원인을 알 수 없다.
        raise ValueError("포스터 기획을 받지 못했습니다 (MODEL_PROFILE 을 확인하세요)")
    return PosterPlan(**raw)
