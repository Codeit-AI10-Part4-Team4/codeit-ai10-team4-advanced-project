"""포스터 광고 부품 — 실사진 카드형과 사진 없는 생성형을 그린다.

사진을 누끼로 바꾸면 여러 상품·상차림·주얼리 세트가 일부 사라질 수 있다.
실사진 포스터는 사진 전체를 둥근 카드 안에 보존하고, 한글 정보는 카드 바깥 종이
영역에 Pillow 로 조판한다. 사진 없는 포스터의 기존 생성형 조판은 그대로 유지한다.
"""

from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFilter

from app_core import compose, fonts
from app_core.palettes import PALETTES
from app_core.photo_enhance import fit_photo_canvas

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


def _scaled(value: int, size: int) -> int:
    return max(1, round(value * size / 1080))


def _photo_card(
    photo: Image.Image,
    card_size: tuple[int, int],
    *,
    radius: int,
    staged: bool,
) -> Image.Image:
    """사진을 자르지 않고 카드에 맞춘다 — 여러 상품과 네 모서리를 모두 보존한다."""
    card = fit_photo_canvas(photo.convert("RGB"), card_size).convert("RGBA")
    if staged:
        # 표기는 생성된 사진 자체에 붙인다. 종이 정보 영역을 가리지 않는다.
        compose.draw_staged_notice(card, "bottom")
    mask = Image.new("L", card_size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, card_size[0] - 1, card_size[1] - 1),
        radius=radius,
        fill=255,
    )
    card.putalpha(mask)
    return card


def generate_uploaded_photo_poster(
    product: Image.Image | None,
    shop: str,
    *,
    tagline: str = "",
    badge: str = "",
    date_line: str = "",
    features: Sequence[str] = (),
    event: str = "",
    headline: str = "",
    product_name: str = "",
    sub: str = "",
    info: str = "",
    palette: str = "retro_green",
    size: int = 1080,
    staged: bool = False,
) -> Image.Image:
    """사장님이 올린 사진 전체를 보존하는 카드형 포스터를 만든다.

    features 는 "제목|설명" 형식의 문자열 목록이다(최대 3개).
    빈 인자는 그 블록을 그리지 않는다 — 없는 정보를 지어내지 않기 위해서다.

    `staged` 는 상품 이미지를 AI 가 그렸는지다(pipeline 이 정해서 준다).
    켜지면 "연출된 이미지" 를 새긴다 — 근거는 compose.draw_staged_notice.
    """
    if palette not in PALETTES:
        raise ValueError(f"모르는 팔레트입니다: {palette!r}")

    cream, dark, red, _gold = PALETTES[palette]
    canvas = paper_background(size, base=cream).convert("RGBA")
    d = ImageDraw.Draw(canvas, "RGBA")
    m = _scaled(_MARGIN, size)
    muted = (92, 92, 88)

    # ── 헤더: 가게명 + 선택 문구. 사진과 분리해 어떤 사진에서도 잘 읽힌다.
    d.text(
        (m + _scaled(6, size), _scaled(52, size)),
        shop,
        font=fonts.fit(shop, _scaled(700, size), _scaled(27, size), "body"),
        fill=muted,
    )
    headline_max = _scaled(690 if badge else 900, size)
    if headline:
        d.text(
            (m + _scaled(6, size), _scaled(91, size)),
            headline,
            font=fonts.fit(headline, headline_max, _scaled(64, size), "body"),
            fill=dark,
        )
    d.rounded_rectangle(
        (
            m + _scaled(6, size),
            _scaled(184, size),
            m + _scaled(96, size),
            _scaled(192, size),
        ),
        radius=_scaled(4, size),
        fill=red,
    )

    if badge:
        rx0, rx1 = size - _scaled(270, size), size - m
        ry0, ry1 = _scaled(54, size), _scaled(116, size)
        d.rounded_rectangle((rx0, ry0, rx1, ry1), radius=_scaled(31, size), fill=red)
        d.text(
            ((rx0 + rx1) // 2, (ry0 + ry1) // 2),
            badge,
            font=fonts.fit(badge, rx1 - rx0 - _scaled(30, size), _scaled(27, size), "body"),
            fill=cream,
            anchor="mm",
        )

    # ── 사진 카드: 누끼를 만들지 않고 원본 사진 전체를 보존한다.
    card_box = (
        m,
        _scaled(220, size),
        size - m,
        _scaled(720, size),
    )
    card_size = (card_box[2] - card_box[0], card_box[3] - card_box[1])
    if product is not None:
        shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (
                card_box[0] + _scaled(4, size),
                card_box[1] + _scaled(10, size),
                card_box[2] + _scaled(4, size),
                card_box[3] + _scaled(10, size),
            ),
            radius=_scaled(34, size),
            fill=(0, 0, 0, 58),
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(_scaled(16, size))))
        card = _photo_card(
            product,
            card_size,
            radius=_scaled(32, size),
            staged=staged,
        )
        canvas.alpha_composite(card, (card_box[0], card_box[1]))

    # ── 사진 아래 정보: 비어 있는 항목은 조용히 생략한다.
    label = tagline or "대표 상품"
    d.text(
        (m + _scaled(6, size), _scaled(757, size)),
        label,
        font=fonts.fit(label, _scaled(890, size), _scaled(25, size), "body_light"),
        fill=red,
    )
    if product_name:
        d.text(
            (m + _scaled(6, size), _scaled(797, size)),
            product_name,
            font=fonts.fit(product_name, _scaled(900, size), _scaled(45, size), "body"),
            fill=dark,
        )
    if sub:
        d.text(
            (m + _scaled(6, size), _scaled(855, size)),
            sub,
            font=fonts.fit(sub, _scaled(900, size), _scaled(27, size), "body_light"),
            fill=muted,
        )

    fact_parts = [part for part in (date_line, event) if part]
    if fact_parts:
        facts = "  ·  ".join(fact_parts)
        d.text(
            (m + _scaled(6, size), _scaled(899, size)),
            facts,
            font=fonts.fit(facts, _scaled(900, size), _scaled(23, size), "body"),
            fill=red,
        )

    feature_parts = []
    for feature in features[:3]:
        title, _, desc = feature.partition("|")
        feature_parts.append(f"{title} — {desc}" if desc else title)
    if feature_parts:
        feature_line = "  ·  ".join(feature_parts)
        d.text(
            (m + _scaled(6, size), _scaled(938, size)),
            feature_line,
            font=fonts.fit(feature_line, _scaled(900, size), _scaled(21, size), "body_light"),
            fill=muted,
        )

    d.line(
        (
            m + _scaled(6, size),
            _scaled(986, size),
            size - m - _scaled(6, size),
            _scaled(986, size),
        ),
        fill=(*dark, 55),
        width=_scaled(2, size),
    )
    if info:
        d.text(
            (m + _scaled(6, size), _scaled(1014, size)),
            f"{shop}  ·  {info}",
            font=fonts.fit(
                f"{shop}  ·  {info}", _scaled(900, size), _scaled(24, size), "body_light"
            ),
            fill=muted,
        )
    elif shop:
        d.text(
            (m + _scaled(6, size), _scaled(1014, size)),
            shop,
            font=fonts.fit(shop, _scaled(900, size), _scaled(24, size), "body_light"),
            fill=muted,
        )

    if staged and product is None:
        compose.draw_staged_notice(canvas, "bottom")

    return canvas.convert("RGB")


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
    """사진 없는 주문의 기존 정보 포스터를 만든다.

    생성된 주인공 이미지는 종이 위 제품 영역에 놓는다. 업로드 실사진은 이 함수가
    아니라 :func:`generate_uploaded_photo_poster`로 보내 누끼 없이 전체를 보존한다.
    """
    if palette not in PALETTES:
        raise ValueError(f"모르는 팔레트입니다: {palette!r}")

    cream, dark, red, gold = PALETTES[palette]
    canvas = paper_background(size, base=cream).convert("RGBA")
    d = ImageDraw.Draw(canvas, "RGBA")
    m = _MARGIN

    if product is not None:
        bbox = product.getbbox()
        p = product.crop(bbox) if bbox else product.copy()
        p.thumbnail((int(size * 0.58), int(size * 0.50)))
        canvas.alpha_composite(p, (size - p.width - 20, 340))

    if badge:
        rx0, rx1 = size - 250, size - m
        bf = fonts.fit(badge, rx1 - rx0 - 32, 42, "display")
        d.rectangle([rx0, 0, rx1, 150], fill=red)
        d.polygon([(rx0, 150), (rx1, 150), ((rx0 + rx1) // 2, 192)], fill=red)
        d.text(((rx0 + rx1) // 2, 74), badge, font=bf, fill=cream, anchor="mm")

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
            (m + 48, y - 12),
            title,
            font=fonts.fit(title, 340, 32, "body"),
            fill=dark,
            anchor="lm",
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
        compose.draw_staged_notice(canvas, "top")

    return canvas.convert("RGB")
