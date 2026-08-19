"""포스터 광고 부품 — 정보가 많은 전단지형 광고를 그린다.

심플형(compose.compose_ad)과 배경 전략이 다르다.
  심플형   AI 생성 사진 배경 — 분위기가 주인공
  포스터형 조용한 종이 배경  — 정보가 주인공. 사진 배경 위에서는 글자가 묻힌다

배치는 비대칭 2단이다 — 좌: 정보 기둥 / 우: 제품.
가운데로만 정렬하면 시선이 흐르지 않고 밋밋해진다.

한글은 생성 모델이 못 그리므로 여기서 PIL 로 얹는다.
그리는 순서가 곧 레이어다 — 배경 → 제품 → 배지 → 좌측 기둥 → 정보바.
실험 근거: notebooks/background_gen_poc.ipynb
"""

from collections.abc import Sequence

from PIL import Image, ImageDraw

from app_core import compose, fonts
from app_core.palettes import PALETTES

_MARGIN = 64


def paper_background(size: int = 1080, base: tuple[int, int, int] = (243, 233, 210)) -> Image.Image:
    """포스터용 종이 배경 — 가장자리를 살짝 눌러 인쇄물 느낌을 낸다."""
    bg = Image.new("RGB", (size, size), base)
    d = ImageDraw.Draw(bg, "RGBA")
    # 크기에 비례해 겹 수를 정한다. 고정값이면 작은 이미지에서 사각형이 뒤집힌다.
    depth = min(90, size // 8)
    for i in range(depth):
        d.rectangle([i, i, size - i, size - i], outline=(0, 0, 0, 3))
    return bg


def generate_poster(
    product: Image.Image | None,
    shop: str,
    *,
    tagline: str = "",
    badge: str = "",
    date_line: str = "",
    features: Sequence[str] = (),
    event: str = "",
    headline: str = "",
    info: str = "",
    palette: str = "retro_green",
    size: int = 1080,
    staged: bool = False,
) -> Image.Image:
    """포스터형 광고를 만든다.

    features 는 "제목|설명" 형식의 문자열 목록이다(최대 3개).
    빈 인자는 그 블록을 그리지 않는다 — 없는 정보를 지어내지 않기 위해서다.

    `staged` 는 상품 이미지를 AI 가 그렸는지다(pipeline 이 정해서 준다).
    켜지면 "연출된 이미지" 를 새긴다 — 근거는 compose.draw_staged_notice.
    """
    if palette not in PALETTES:
        raise ValueError(f"모르는 팔레트입니다: {palette!r}")

    cream, dark, red, gold = PALETTES[palette]
    canvas = paper_background(size, base=cream).convert("RGBA")
    d = ImageDraw.Draw(canvas, "RGBA")
    m = _MARGIN

    # ── 우측: 제품 (먼저 깔고 글자를 위에 얹는다)
    if product is not None:
        bbox = product.getbbox()
        p = product.crop(bbox) if bbox else product.copy()
        p.thumbnail((int(size * 0.58), int(size * 0.50)))
        canvas.alpha_composite(p, (size - p.width - 20, 340))

    # ── 우상단 리본 배지
    if badge:
        rx0, rx1 = size - 250, size - m
        bf = fonts.fit(badge, rx1 - rx0 - 32, 42, "display")
        d.rectangle([rx0, 0, rx1, 150], fill=red)
        d.polygon([(rx0, 150), (rx1, 150), ((rx0 + rx1) // 2, 192)], fill=red)
        d.text(((rx0 + rx1) // 2, 74), badge, font=bf, fill=cream, anchor="mm")

    # ── 좌측 정보 기둥
    if tagline:
        d.text(
            (m, 118),
            tagline,
            font=fonts.fit(tagline, 430, 46, "script"),
            fill=dark,
            anchor="lm",
        )
    d.text((m, 196), shop, font=fonts.fit(shop, 470, 82, "display"), fill=dark, anchor="lm")
    d.line([(m, 246), (m + 330, 246)], fill=gold, width=4)

    if date_line:
        d.rounded_rectangle([m, 292, m + 380, 402], 10, outline=dark, width=3)
        d.text(
            (m + 190, 347),
            date_line,
            font=fonts.fit(date_line, 330, 44, "display"),
            fill=red,
            anchor="mm",
        )

    for i, feat in enumerate(features[:3]):
        title, _, desc = feat.partition("|")
        y = 470 + i * 100
        d.ellipse([m, y - 14, m + 28, y + 14], fill=dark)
        d.text(
            (m + 48, y - 12), title, font=fonts.fit(title, 340, 32, "body"), fill=dark, anchor="lm"
        )
        if desc:
            d.text(
                (m + 48, y + 20),
                desc,
                font=fonts.fit(desc, 360, 24, "body_light"),
                fill=(120, 110, 92),
                anchor="lm",
            )

    if event:
        d.rounded_rectangle([m, 790, m + 400, 880], 12, fill=red)
        d.text(
            (m + 200, 835),
            event,
            font=fonts.fit(event, 350, 34, "display"),
            fill=cream,
            anchor="mm",
        )

    # ── 하단 정보바
    bar_h = 180 if headline else 120
    d.rectangle([0, size - bar_h, size, size], fill=dark)
    if headline:
        d.text(
            (size // 2, size - 118),
            headline,
            font=fonts.fit(headline, int(size * 0.9), 54, "display"),
            fill=(255, 255, 255),
            anchor="mm",
        )
    if info:
        d.text(
            (size // 2, size - 46),
            info,
            font=fonts.fit(info, int(size * 0.9), 26, "body_light"),
            fill=(220, 224, 216),
            anchor="mm",
        )
    if staged:
        # 좌상단 — 배지는 우상단, 문구·정보 줄은 가운데 정렬이라 여기가 비어 있다
        # (태그라인이 y=118 부터라 그 위가 한산하다).
        compose.draw_staged_notice(canvas, "top")

    return canvas.convert("RGB")
