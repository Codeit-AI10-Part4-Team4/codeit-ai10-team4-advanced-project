"""광고 생성 총괄 부품 — 주문서를 받아 부품들을 순서대로 돌려 완성 광고를 만든다.

주문서(AdBrief)는 "무엇을 원하는가", 가게(Store)는 "어떤 가게인가",
문구(CopyCandidate)는 "이미지에 얹을 글"이다. 셋이 모여야 광고 한 장이 나온다.

형태는 두 가지다.
  simple  AI 생성 사진 배경 + 문구 — 분위기가 주인공. 배경 생성에 GPU 를 쓴다
  poster  종이 배경 + 정보 블록   — 정보가 주인공. 확산 모델을 쓰지 않아 빠르고 싸다
"""

from typing import Literal

from PIL import Image

from app_core import photo_store
from app_core.background import remove_background
from app_core.compose import compose_ad
from app_core.gen_background import generate_background
from app_core.photo_router import mask_area, remove_crumbs, route_photo
from app_core.poster import generate_poster
from app_core.poster_plan import plan_poster
from app_core.prompt_builder import build_bg_prompt, build_hero_prompt
from app_core.schema import AdBrief, CopyCandidate, Store

Style = Literal["simple", "poster"]


def _info_line(store: Store) -> str:
    """포스터 하단 한 줄 — 없는 항목은 빼고 이어 붙인다."""
    return "  ·  ".join(part for part in (store.address, store.phone) if part)


def _simple_ad(brief: AdBrief, store: Store, copy: CopyCandidate, product: Image.Image | None):
    """제품 누끼가 있으면 빈 무대 배경에 얹고, 없으면 제품이 든 장면을 통째로 그린다.

    빈 무대 프롬프트(_BASE)는 누끼를 얹으려고 제품을 일부러 뺀 캔버스다. 제품 없이
    그대로 쓰면 광고 대상이 사라진다 — generate 갈래·사진 없는 주문이 그 경우라,
    그때는 hero 프롬프트로 제품이 화면에 있게 그린다.
    """
    if product is None:
        prompt = build_hero_prompt(store.industry_label, brief.product, brief.tone)
    else:
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


_MIME = {".png": "image/png", ".webp": "image/webp"}


def generate_ad(
    brief: AdBrief,
    store: Store,
    copy: CopyCandidate,
    style: Style = "simple",
) -> Image.Image:
    """주문서·가게·문구를 받아 완성 광고 이미지를 돌려준다.

    사진이 있으면 갈래 판정(photo_router)이 사용법을 정한다 —
      keep      원본을 배경으로 그대로 쓴다 (확산 모델도 안 부른다)
      cutout    청소한 누끼를 새 배경에 얹는다
      generate  사진을 참고하지 않고 새로 그린다
    포스터형은 원본을 배경으로 쓸 수 없는 형태라 갈래와 무관하게 누끼를 쓰고,
    누끼가 빈손이면 주인공을 생성해 채운다.
    """
    photo = cut = route = None
    if brief.photo_id is not None:
        path = photo_store.path_of(brief.photo_id)
        if path is None:
            raise FileNotFoundError(f"보관함에 {brief.photo_id}번 사진이 없습니다")
        photo = Image.open(path)
        # 판정은 **청소 전** 누끼로 한다 — 먼저 청소하면 라우터가 보기도 전에 상품이 사라진다
        raw_cut = remove_background(photo)
        if style == "simple":
            mime = _MIME.get(path.suffix.lower(), "image/jpeg")
            route = route_photo(path.read_bytes(), mime, raw_cut)
        cut = remove_crumbs(raw_cut)

    if style == "poster":
        # 누끼가 빈손(전경 5% 미만)이면 없는 셈 친다 — 실오라기가 제품 자리에 앉는 것 방지
        product = cut if cut is not None and mask_area(cut) >= 0.05 else None
        return _poster_ad(brief, store, copy, product)

    if route == "keep" and photo is not None:
        # 사진이 이미 광고 배경감 — 확산 모델 없이 원본 위에 문구만 얹는다
        return compose_ad(None, copy.headline, copy.sub, background=photo.convert("RGB"))
    return _simple_ad(brief, store, copy, cut if route == "cutout" else None)
