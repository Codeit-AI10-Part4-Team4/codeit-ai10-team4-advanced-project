"""포스터 광고 부품 — 정보가 많은 전단지형 광고를 그린다.

심플형(compose.compose_ad)과 배경 전략이 다르다.
  심플형   AI 생성 사진 배경 — 분위기가 주인공
  포스터형 조용한 종이 배경  — 정보가 주인공. 사진 배경 위에서는 글자가 묻힌다

한글은 생성 모델이 못 그리므로 여기서 PIL 로 얹는다.
그리는 순서가 곧 레이어다 — 배경 → 글로우 → 제품 → 스티커 → 정보바.
실험 근거: notebooks/background_gen_poc.ipynb
"""

from PIL import Image, ImageDraw, ImageFilter

from app_core import fonts

# 색은 세 가지로 고정한다. 배경색이 매번 달라지면 요소끼리 따로 논다.
CREAM = (243, 233, 210)
DARK = (44, 58, 46)
RED = (150, 38, 30)
GOLD = (198, 154, 60)


def paper_background(size: int = 1080, base: tuple[int, int, int] = CREAM) -> Image.Image:
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
    headline: str,
    sub: str = "",
    tagline: str = "",
    badge: str = "",
    info: str = "",
    event: str = "",
    size: int = 1080,
) -> Image.Image:
    """포스터형 광고를 만든다. 빈 인자는 그 블록을 그리지 않는다."""
    canvas = paper_background(size).convert("RGBA")
    d = ImageDraw.Draw(canvas, "RGBA")

    if tagline:
        d.text(
            (size // 2, 78),
            tagline,
            font=fonts.fit(tagline, int(size * 0.7), 52, "script"),
            fill=(130, 112, 84),
            anchor="mm",
        )

    d.text(
        (size // 2, 152),
        shop,
        font=fonts.fit(shop, int(size * 0.84), 96, "display"),
        fill=DARK,
        anchor="mm",
    )
    d.line([(size * 0.30, 214), (size * 0.70, 214)], fill=GOLD, width=3)

    if badge:
        bf = fonts.load("display", 36)
        bw = int(bf.getlength(badge)) + 56
        d.rounded_rectangle([(size - bw) // 2, 236, (size + bw) // 2, 300], 32, fill=RED)
        d.text((size // 2, 268), badge, font=bf, fill=CREAM, anchor="mm")

    # 제품 뒤 스포트라이트 — 흐리게 깔아 시선을 모은다 (제품보다 먼저 그린다)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([size * 0.13, 340, size * 0.87, 830], fill=(214, 199, 170, 120))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))

    if product is not None:
        bbox = product.getbbox()
        p = product.crop(bbox) if bbox else product.copy()
        p.thumbnail((int(size * 0.92), int(size * 0.58)))
        canvas.alpha_composite(p, ((size - p.width) // 2, 860 - p.height))

    if event:
        cx, cy, r = 178, 700, 118
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
        d.ellipse([cx - r + 9, cy - r + 9, cx + r - 9, cy + r - 9], outline=CREAM, width=3)
        for i, line in enumerate(event.split("\n")):
            d.text(
                (cx, cy - 24 + i * 42),
                line,
                font=fonts.fit(line, r * 2 - 44, 38, "display"),
                fill=CREAM,
                anchor="mm",
            )

    d.rectangle([0, size - 230, size, size], fill=DARK)
    d.text(
        (size // 2, size - 168),
        headline,
        font=fonts.fit(headline, int(size * 0.88), 64, "display"),
        fill=(255, 255, 255),
        anchor="mm",
    )
    if sub:
        d.text(
            (size // 2, size - 104),
            sub,
            font=fonts.fit(sub, int(size * 0.88), 38, "body"),
            fill=GOLD,
            anchor="mm",
        )
    if info:
        d.text(
            (size // 2, size - 46),
            info,
            font=fonts.fit(info, int(size * 0.92), 26, "body_light"),
            fill=(200, 208, 198),
            anchor="mm",
        )

    return canvas.convert("RGB")
