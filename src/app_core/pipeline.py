"""광고 생성 총괄 부품 — 주문 내용을 받아 부품들을 순서대로 돌려 완성 광고를 만든다.

지금은 낱개 인자를 받지만, 주문서(AdBrief)에 photo_id 칸이 생기면
AdBrief 하나를 받는 형태로 바꿀 예정이다.
"""

from PIL import Image

from app_core.background import remove_background
from app_core.compose import compose_ad
from app_core.gen_background import generate_background
from app_core.photo_store import load_photo
from app_core.prompt_builder import build_bg_prompt


def generate_ad(
    industry: str,
    headline: str,
    sub: str = "",
    situation: str = "",
    tone: str = "",
    photo_id: int | None = None,
) -> Image.Image:
    """주문 내용 하나를 받아 완성 광고 이미지를 돌려준다."""
    prompt = build_bg_prompt(industry, situation, tone)
    bg = generate_background(prompt)
    if photo_id is None:
        raise NotImplementedError("사진 없는 통생성은 아직 준비 중입니다")
    product = remove_background(load_photo(photo_id))
    return compose_ad(product, headline, sub, background=bg)
