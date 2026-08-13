"""광고 생성 총괄 부품 — 주문서를 받아 부품들을 순서대로 돌려 완성 광고를 만든다.

주문서(AdBrief)는 "무엇을 원하는가", 가게(Store)는 "어떤 가게인가",
문구(CopyCandidate)는 "이미지에 얹을 글"이다. 셋이 모여야 광고 한 장이 나온다.

형태는 두 가지다.
  simple  AI 생성 사진 배경 + 문구 — 분위기가 주인공. 배경 생성에 GPU 를 쓴다
  poster  종이 배경 + 정보 블록   — 정보가 주인공. 확산 모델을 쓰지 않아 빠르고 싸다
"""

from typing import Literal

from PIL import Image

from app_core.background import remove_background
from app_core.compose import compose_ad
from app_core.gen_background import generate_background
from app_core.photo_store import load_photo
from app_core.poster import generate_poster
from app_core.poster_plan import plan_poster
from app_core.prompt_builder import build_bg_prompt, build_hero_prompt
from app_core.schema import AdBrief, CopyCandidate, Store

Style = Literal["simple", "poster"]


def _info_line(store: Store) -> str:
    """포스터 하단 한 줄 — 없는 항목은 빼고 이어 붙인다."""
    return "  ·  ".join(part for part in (store.address, store.phone) if part)


def _simple_ad(brief: AdBrief, store: Store, copy: CopyCandidate, product: Image.Image | None):
    prompt = build_bg_prompt(store.industry_label, brief.situation, brief.tone)
    bg = generate_background(prompt)
    return compose_ad(product, copy.headline, copy.sub, background=bg)


def _poster_ad(brief: AdBrief, store: Store, copy: CopyCandidate, product: Image.Image | None):
    """포스터에 들어갈 내용(태그라인·특징·이벤트·색)은 기획 부품이 정한다.

    사장님에게 특징 3개를 직접 쓰게 하면 서비스가 아니라 양식 작성이 된다.
    """
    if product is None:
        # 사진이 없으면 주인공 이미지를 생성해 그 자리를 채운다 (사진 카드처럼 얹힌다)
        hero_prompt = build_hero_prompt(store.industry_label, brief.product, brief.tone)
        product = generate_background(hero_prompt).convert("RGBA")

    plan = plan_poster(
        shop=store.name,
        industry=store.industry_label,
        product=brief.product,
        situation=brief.situation,
        tone=brief.tone,
        extra=brief.extra,
        transcript=brief.raw_utterance,
    )
    return generate_poster(
        product,
        store.name,
        tagline=plan.tagline,
        badge=plan.badge,
        date_line=plan.date_line,
        features=plan.features,
        event=plan.event,
        headline=copy.headline,
        info=_info_line(store),
        palette=plan.palette,
    )


def generate_ad(
    brief: AdBrief,
    store: Store,
    copy: CopyCandidate,
    style: Style = "simple",
) -> Image.Image:
    """주문서·가게·문구를 받아 완성 광고 이미지를 돌려준다.

    사진(photo_id)이 없으면 제품 없이 만든다 — 텍스트만으로 주문한 경우다.
    """
    product = None if brief.photo_id is None else remove_background(load_photo(brief.photo_id))
    if style == "poster":
        return _poster_ad(brief, store, copy, product)
    return _simple_ad(brief, store, copy, product)
