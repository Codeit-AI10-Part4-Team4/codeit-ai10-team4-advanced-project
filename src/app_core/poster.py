"""포스터 광고 부품 — 실사진 카드형과 사진 없는 생성형을 그린다.

사진을 누끼로 바꾸면 여러 상품·상차림·주얼리 세트가 일부 사라질 수 있다.
사진은 전체를 둥근 카드에 넣고, 사진 유무와 관계없이 같은 따뜻한 종이 포스터에
한글·가격·상호를 Pillow로 정확하게 조판한다.
"""

import re
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFilter

from app_core import compose, fonts
from app_core.palettes import PALETTES
from app_core.photo_enhance import fit_photo_canvas


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


def _without_repeated_price(text: str, price_text: str) -> str:
    """큰 가격 칸에 표시할 금액은 헤드라인·설명에서 한 번 더 쓰지 않는다."""
    if not price_text:
        return text

    variants = {
        price_text,
        price_text.replace(",", ""),
        price_text.replace("원", " 원"),
    }
    compact = text
    for variant in sorted(variants, key=len, reverse=True):
        compact = compact.replace(variant, "")
    compact = re.sub(r"\s{2,}", " ", compact)
    return compact.strip(" \t·|/,-–—:")


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


def _draw_editorial_frame(
    draw: ImageDraw.ImageDraw,
    *,
    size: int,
    dark: tuple[int, int, int],
    gold: tuple[int, int, int],
) -> None:
    """따뜻한 종이 포스터의 이중 테두리와 모서리 장식을 그린다."""
    outer = _scaled(38, size)
    inner = _scaled(54, size)
    draw.rounded_rectangle(
        (outer, outer, size - outer, size - outer),
        radius=_scaled(14, size),
        outline=(*dark, 210),
        width=_scaled(3, size),
    )
    draw.rounded_rectangle(
        (inner, inner, size - inner, size - inner),
        radius=_scaled(10, size),
        outline=(*gold, 180),
        width=_scaled(2, size),
    )

    arm = _scaled(34, size)
    for x, y, sx, sy in (
        (inner, inner, 1, 1),
        (size - inner, inner, -1, 1),
        (inner, size - inner, 1, -1),
        (size - inner, size - inner, -1, -1),
    ):
        draw.line((x, y + sy * arm, x, y, x + sx * arm, y), fill=dark, width=_scaled(4, size))


def _generate_editorial_poster(
    photo: Image.Image | None,
    shop: str,
    *,
    headline: str,
    product_name: str,
    sub: str,
    price_text: str,
    info: str,
    tagline: str,
    badge: str,
    date_line: str,
    features: Sequence[str],
    event: str,
    palette: str,
    size: int,
    staged: bool,
) -> Image.Image:
    """사진 유무와 관계없이 같은 따뜻한 정보 포스터 틀로 조판한다."""
    if palette not in PALETTES:
        raise ValueError(f"모르는 팔레트입니다: {palette!r}")

    cream, dark, accent, gold = PALETTES[palette]
    paper = tuple(round(channel + (255 - channel) * 0.42) for channel in cream)
    canvas = paper_background(size, base=cream).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    panel = _scaled(46, size)
    draw.rounded_rectangle(
        (panel, panel, size - panel, size - panel),
        radius=_scaled(18, size),
        fill=(*paper, 245),
    )
    _draw_editorial_frame(draw, size=size, dark=dark, gold=gold)

    display_headline = _without_repeated_price(headline, price_text)
    display_sub = _without_repeated_price(sub, price_text)
    title = display_headline or tagline or product_name or shop
    if title:
        draw.text(
            (size // 2, _scaled(123, size)),
            title,
            font=fonts.fit(title, _scaled(820, size), _scaled(66, size), "body"),
            fill=dark,
            anchor="mm",
        )

    ornament_y = _scaled(174, size)
    center = size // 2
    line = _scaled(92, size)
    gap = _scaled(18, size)
    draw.line((center - line, ornament_y, center - gap, ornament_y), fill=gold, width=2)
    draw.line((center + gap, ornament_y, center + line, ornament_y), fill=gold, width=2)
    diamond = _scaled(5, size)
    draw.polygon(
        (
            (center, ornament_y - diamond),
            (center + diamond, ornament_y),
            (center, ornament_y + diamond),
            (center - diamond, ornament_y),
        ),
        fill=accent,
    )

    card_box = (
        _scaled(160, size),
        _scaled(198, size),
        size - _scaled(160, size),
        _scaled(704, size),
    )
    card_size = (card_box[2] - card_box[0], card_box[3] - card_box[1])
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (
            card_box[0] + _scaled(3, size),
            card_box[1] + _scaled(8, size),
            card_box[2] + _scaled(3, size),
            card_box[3] + _scaled(8, size),
        ),
        radius=_scaled(22, size),
        fill=(42, 25, 16, 45),
    )
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(_scaled(12, size))))

    if photo is not None:
        card = _photo_card(photo, card_size, radius=_scaled(20, size), staged=staged)
        canvas.alpha_composite(card, (card_box[0], card_box[1]))
    else:
        draw.rounded_rectangle(
            card_box,
            radius=_scaled(20, size),
            fill=(*cream, 180),
            outline=(*gold, 150),
            width=_scaled(2, size),
        )

    if badge:
        badge_left = card_box[0] + _scaled(22, size)
        badge_top = card_box[1] + _scaled(20, size)
        badge_right = badge_left + _scaled(160, size)
        badge_bottom = badge_top + _scaled(48, size)
        draw.rounded_rectangle(
            (badge_left, badge_top, badge_right, badge_bottom),
            radius=_scaled(22, size),
            fill=accent,
        )
        draw.text(
            ((badge_left + badge_right) // 2, (badge_top + badge_bottom) // 2),
            badge,
            font=fonts.fit(badge, _scaled(130, size), _scaled(22, size), "body"),
            fill=paper,
            anchor="mm",
        )

    info_box = (
        _scaled(104, size),
        _scaled(728, size),
        size - _scaled(104, size),
        _scaled(930, size),
    )
    draw.rounded_rectangle(
        info_box,
        radius=_scaled(18, size),
        fill=(*cream, 235),
        outline=(*gold, 190),
        width=_scaled(2, size),
    )

    text_left = info_box[0] + _scaled(30, size)
    has_price = bool(price_text.strip())
    text_width = _scaled(520 if has_price else 800, size)
    if product_name:
        draw.text(
            (text_left, _scaled(780, size)),
            product_name,
            font=fonts.fit(product_name, text_width, _scaled(34, size), "body"),
            fill=dark,
            anchor="lm",
        )
    detail = display_sub or tagline
    if detail:
        draw.text(
            (text_left, _scaled(828, size)),
            detail,
            font=fonts.fit(detail, text_width, _scaled(26, size), "body_light"),
            fill=dark,
            anchor="lm",
        )

    facts = [part for part in (date_line, event) if part]
    facts.extend(feature.partition("|")[0] for feature in features[:2] if feature)
    if facts:
        fact_line = "  ·  ".join(facts)
        draw.text(
            (text_left, _scaled(878, size)),
            fact_line,
            font=fonts.fit(fact_line, text_width, _scaled(21, size), "body_light"),
            fill=accent,
            anchor="lm",
        )

    if has_price:
        price_x = info_box[2] - _scaled(30, size)
        draw.line(
            (
                price_x - _scaled(245, size),
                _scaled(760, size),
                price_x - _scaled(245, size),
                _scaled(900, size),
            ),
            fill=(*gold, 130),
            width=_scaled(2, size),
        )
        draw.text(
            (price_x, _scaled(824, size)),
            price_text,
            font=fonts.fit(price_text, _scaled(220, size), _scaled(61, size), "display"),
            fill=accent,
            anchor="rm",
        )

    draw.text(
        (size // 2, _scaled(974, size)),
        shop,
        font=fonts.fit(shop, _scaled(760, size), _scaled(29, size), "body"),
        fill=dark,
        anchor="mm",
    )
    if info:
        draw.text(
            (size // 2, _scaled(1012, size)),
            info,
            font=fonts.fit(info, _scaled(820, size), _scaled(19, size), "body_light"),
            fill=dark,
            anchor="mm",
        )

    if staged and photo is None:
        compose.draw_staged_notice(canvas, "bottom")

    return canvas.convert("RGB")


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
    price_text: str = "",
    info: str = "",
    palette: str = "warm_bakery",
    size: int = 1080,
    staged: bool = False,
) -> Image.Image:
    """업로드 사진을 따뜻한 정보 포스터의 사진 카드로 사용한다."""
    return _generate_editorial_poster(
        product,
        shop,
        headline=headline,
        product_name=product_name,
        sub=sub,
        price_text=price_text,
        info=info,
        tagline=tagline,
        badge=badge,
        date_line=date_line,
        features=features,
        event=event,
        palette=palette,
        size=size,
        staged=staged,
    )


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
    product_name: str = "",
    sub: str = "",
    price_text: str = "",
    info: str = "",
    palette: str = "warm_bakery",
    size: int = 1080,
    staged: bool = False,
) -> Image.Image:
    """사진 없이 생성한 주인공도 업로드 사진과 같은 정보 포스터로 조판한다."""
    return _generate_editorial_poster(
        product,
        shop,
        headline=headline,
        product_name=product_name,
        sub=sub,
        price_text=price_text,
        info=info,
        tagline=tagline,
        badge=badge,
        date_line=date_line,
        features=features,
        event=event,
        palette=palette,
        size=size,
        staged=staged,
    )
