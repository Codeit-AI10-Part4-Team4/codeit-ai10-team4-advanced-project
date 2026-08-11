"""광고 생성 총괄 부품 — 주문서를 받아 부품들을 순서대로 돌려 완성 광고를 만든다.

주문서(AdBrief)는 "무엇을 원하는가", 가게(Store)는 "어떤 가게인가",
문구(CopyCandidate)는 "이미지에 얹을 글"이다. 셋이 모여야 광고 한 장이 나온다.
"""

from PIL import Image

from app_core.background import remove_background
from app_core.compose import compose_ad
from app_core.gen_background import generate_background
from app_core.photo_store import load_photo
from app_core.prompt_builder import build_bg_prompt
from app_core.schema import AdBrief, CopyCandidate, Store


def generate_ad(
    brief: AdBrief,
    store: Store,
    copy: CopyCandidate,
) -> Image.Image:
    """주문서·가게·문구를 받아 완성 광고 이미지를 돌려준다."""
    prompt = build_bg_prompt(store.industry_label, brief.situation, brief.tone)
    bg = generate_background(prompt)

    if brief.photo_id is None:
        raise NotImplementedError("사진 없는 통생성은 아직 준비 중입니다")

    product = remove_background(load_photo(brief.photo_id))
    return compose_ad(product, copy.headline, copy.sub, background=bg)
