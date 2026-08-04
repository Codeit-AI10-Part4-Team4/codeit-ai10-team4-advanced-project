"""레이아웃 합성 엔진 (PIL).

P0 기능 — Diffusion 모델은 한글을 제대로 그리지 못하므로,
이미지는 '글자 없는 배경'으로 만들고 한글은 여기서 얹는다.

이 분리 덕분에 사용자가 문구만 바꿔 재출력할 때 GPU 를 다시 돌릴 필요가 없다.

배치 패턴은 규격마다 만들지 않고 4개를 공유한다.
패턴 구성의 근거는 docs/01_타깃사용자_및_기능정의.md 3장(두 개의 축) 참조.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

# 맑은 고딕 → 나눔고딕 → 굴림 순으로 탐색 (Windows 기본 탑재)
_FONT_CANDIDATES = {
    "regular": ["C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/NanumGothic.ttf"],
    "bold": ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/NanumGothicBold.ttf"],
}


def _font_path(weight: str) -> str:
    for p in _FONT_CANDIDATES[weight]:
        if Path(p).exists():
            return p
    for p in _FONT_CANDIDATES["regular"]:
        if Path(p).exists():
            return p
    raise FileNotFoundError(
        "한글 폰트를 찾지 못했습니다. assets/fonts/ 에 TTF 를 넣고 _FONT_CANDIDATES 에 추가하세요."
    )


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path("bold" if bold else "regular"), size)


def _hex(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha)


# ──────────────────────────────────────────────────────────────
# 텍스트 배치 헬퍼
# ──────────────────────────────────────────────────────────────

def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """한국어는 어절 단위로 끊되, 한 어절이 너무 길면 글자 단위로 자른다."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
            while draw.textlength(cur, font=font) > max_width and len(cur) > 1:
                cut = len(cur)
                while cut > 1 and draw.textlength(cur[:cut], font=font) > max_width:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
        if cur:
            lines.append(cur)
    return lines


def _fit(draw, text: str, max_width: int, start: int, bold: bool, max_lines: int):
    """줄 수 제한 안에 들어올 때까지 폰트 크기를 줄인다."""
    size = start
    while size > 10:
        font = _font(size, bold)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size = int(size * 0.92)
    font = _font(10, bold)
    return font, _wrap(draw, text, font, max_width)[:max_lines]


def _draw_lines(draw, lines, font, x, y, fill, spacing: float = 1.25, anchor_x="left", box_w=0):
    lh = int(font.size * spacing)
    for line in lines:
        px = x
        if anchor_x == "center":
            px = x + (box_w - draw.textlength(line, font=font)) / 2
        draw.text((px, y), line, font=font, fill=fill)
        y += lh
    return y


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """비율 유지하며 캔버스를 꽉 채우도록 크롭."""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    nw, nh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def _band(size: tuple[int, int], color: str, height: int, from_top: bool = False) -> Image.Image:
    """텍스트 가독성 확보용 그라디언트 띠 (아래로 갈수록 진해짐)."""
    w, h = size
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(height):
        ratio = i / max(height - 1, 1)
        alpha = int(235 * (ratio if not from_top else 1 - ratio) ** 1.4)
        y = (h - height + i) if not from_top else i
        d.line([(0, y), (w, y)], fill=_hex(color, alpha))
    return overlay


# ──────────────────────────────────────────────────────────────
# 배치 패턴 4종
# ──────────────────────────────────────────────────────────────

def _layout_bottom_band(canvas, fmt, style, headline, sub, items, badge):
    """하단 반투명 띠 + 헤드라인 — 이미지 중심 (인스타 피드, 배달앱 썸네일)"""
    w, h = canvas.size
    pal, safe = style["palette"], fmt["safe_area"]
    mx = int(w * safe["l"])
    box_w = w - mx * 2

    tmp = ImageDraw.Draw(canvas)
    hf, hl = _fit(tmp, headline, box_w, int(w * 0.095), True, 2)
    sf, sl = (_fit(tmp, sub, box_w, int(w * 0.045), False, 2) if sub else (None, []))

    price_line = " · ".join(f"{i['name']} {i['price']}" for i in items[:2] if i.get("name"))
    pf, pl = (_fit(tmp, price_line, box_w, int(w * 0.058), True, 1) if price_line else (None, []))

    text_h = len(hl) * int(hf.size * 1.25)
    text_h += (len(sl) * int(sf.size * 1.35) + int(h * 0.015)) if sl else 0
    text_h += (len(pl) * int(pf.size * 1.3) + int(h * 0.015)) if pl else 0
    band_h = min(int(h * 0.62), text_h + int(h * safe["b"] * 2.2))

    canvas.alpha_composite(_band(canvas.size, pal["band"], band_h))
    d = ImageDraw.Draw(canvas)

    y = h - band_h + int(band_h - text_h) // 2
    y = _draw_lines(d, hl, hf, mx, y, (255, 255, 255, 255))
    if sl:
        y += int(h * 0.015)
        y = _draw_lines(d, sl, sf, mx, y, (255, 255, 255, 215))
    if pl:
        y += int(h * 0.015)
        _draw_lines(d, pl, pf, mx, y, _hex(pal["accent"]))

    if badge:
        _draw_badge(canvas, badge, mx, int(h * safe["t"]), pal, int(w * 0.035))
    return canvas


def _layout_top_bottom(canvas, fmt, style, headline, sub, items, badge):
    """상단 헤드라인 + 하단 정보 — 스토리, A4 전단지"""
    w, h = canvas.size
    pal, safe = style["palette"], fmt["safe_area"]
    mx = int(w * safe["l"])
    box_w = w - mx * 2

    top_h = int(h * 0.26)
    bot_h = int(h * 0.24)
    canvas.alpha_composite(_band(canvas.size, pal["band"], top_h, from_top=True))
    canvas.alpha_composite(_band(canvas.size, pal["band"], bot_h))

    d = ImageDraw.Draw(canvas)
    hf, hl = _fit(d, headline, box_w, int(w * 0.10), True, 2)
    y = int(h * safe["t"])
    y = _draw_lines(d, hl, hf, mx, y, (255, 255, 255, 255), anchor_x="center", box_w=box_w)

    if badge:
        _draw_badge(canvas, badge, mx, y + int(h * 0.01), pal, int(w * 0.035), center_w=box_w)

    d = ImageDraw.Draw(canvas)
    by = h - bot_h + int(h * 0.035)
    if sub:
        sf, sl = _fit(d, sub, box_w, int(w * 0.048), False, 2)
        by = _draw_lines(d, sl, sf, mx, by, (255, 255, 255, 225), anchor_x="center", box_w=box_w)
    price_line = " · ".join(f"{i['name']} {i['price']}" for i in items[:2] if i.get("name"))
    if price_line:
        pf, pl = _fit(d, price_line, box_w, int(w * 0.062), True, 1)
        _draw_lines(d, pl, pf, mx, by + int(h * 0.012), _hex(pal["accent"]), anchor_x="center", box_w=box_w)
    return canvas


def _layout_side_panel(canvas, fmt, style, headline, sub, items, badge):
    """이미지 좌측 58% + 우측 텍스트 패널 — 가로 배너"""
    w, h = canvas.size
    pal, safe = style["palette"], fmt["safe_area"]
    img_w = int(w * 0.58)

    panel = Image.new("RGBA", (w - img_w, h), _hex(pal["bg"]))
    canvas.paste(panel, (img_w, 0))

    pad = int(w * 0.035)
    box_w = (w - img_w) - pad * 2
    d = ImageDraw.Draw(canvas)

    hf, hl = _fit(d, headline, box_w, int(w * 0.062), True, 3)
    sf, sl = (_fit(d, sub, box_w, int(w * 0.028), False, 3) if sub else (None, []))
    price_line = " · ".join(f"{i['name']} {i['price']}" for i in items[:2] if i.get("name"))
    pf, pl = (_fit(d, price_line, box_w, int(w * 0.038), True, 1) if price_line else (None, []))

    total = len(hl) * int(hf.size * 1.25)
    total += (len(sl) * int(sf.size * 1.35) + int(h * 0.03)) if sl else 0
    total += (len(pl) * int(pf.size * 1.3) + int(h * 0.03)) if pl else 0

    y = (h - total) // 2
    y = _draw_lines(d, hl, hf, img_w + pad, y, _hex(pal["text"]))
    if sl:
        y += int(h * 0.03)
        y = _draw_lines(d, sl, sf, img_w + pad, y, _hex(pal["text"], 190))
    if pl:
        y += int(h * 0.03)
        _draw_lines(d, pl, pf, img_w + pad, y, _hex(pal["accent"]))

    if badge:
        _draw_badge(canvas, badge, int(w * safe["l"]), int(h * safe["t"]), pal, int(h * 0.055))
    return canvas


def _layout_list_grid(canvas, fmt, style, headline, sub, items, badge):
    """항목·가격 반복 배치 — 메뉴판, 특가 POP (정보 중심)"""
    w, h = canvas.size
    pal, safe = style["palette"], fmt["safe_area"]
    mx = int(w * safe["l"])
    box_w = w - mx * 2

    hero_h = int(h * 0.34)
    base = canvas.copy()
    canvas.paste(Image.new("RGBA", (w, h), _hex(pal["bg"])), (0, 0))
    canvas.paste(_cover(base, (w, hero_h)), (0, 0))
    canvas.alpha_composite(_band((w, hero_h), pal["band"], int(hero_h * 0.7)))

    d = ImageDraw.Draw(canvas)
    hf, hl = _fit(d, headline, box_w, int(w * 0.085), True, 2)
    hy = hero_h - int(hf.size * 1.25) * len(hl) - int(h * 0.03)
    _draw_lines(d, hl, hf, mx, hy, (255, 255, 255, 255))

    y = hero_h + int(h * 0.05)
    if sub:
        sf, sl = _fit(d, sub, box_w, int(w * 0.040), False, 2)
        y = _draw_lines(d, sl, sf, mx, y, _hex(pal["text"], 190)) + int(h * 0.02)

    rows = [i for i in items if i.get("name")]
    if not rows:
        return canvas

    # 항목이 적으면 행을 키우고, 남는 세로 공간에 중앙 정렬한다
    avail = h - y - int(h * safe["b"])
    row_size = max(20, min(int(w * 0.075), int(avail / max(len(rows), 1) / 1.6)))
    block_h = int(row_size * 1.6) * len(rows)
    y += max(0, (avail - block_h) // 2)

    nf, vf = _font(row_size, False), _font(int(row_size * 1.06), True)
    for it in rows:
        d.text((mx, y), it["name"], font=nf, fill=_hex(pal["text"]))
        price = it.get("price", "")
        pw = d.textlength(price, font=vf)
        d.text((w - mx - pw, y), price, font=vf, fill=_hex(pal["accent"]))
        dot_y = y + row_size * 0.62
        x0 = mx + d.textlength(it["name"], font=nf) + row_size * 0.3
        x1 = w - mx - pw - row_size * 0.3
        if x1 > x0:
            d.line([(x0, dot_y), (x1, dot_y)], fill=_hex(pal["text"], 60), width=max(1, row_size // 22))
        y += int(row_size * 1.6)

    if badge:
        _draw_badge(canvas, badge, mx, int(h * safe["t"]), pal, int(w * 0.038))
    return canvas


def _draw_badge(canvas, text, x, y, pal, size, center_w: int = 0):
    """강조 뱃지 (알약 모양)."""
    d = ImageDraw.Draw(canvas)
    f = _font(size, True)
    tw = d.textlength(text, font=f)
    pad_x, pad_y = int(size * 0.7), int(size * 0.42)
    bw, bh = int(tw + pad_x * 2), int(size + pad_y * 2)
    if center_w:
        x = x + (center_w - bw) // 2
    d.rounded_rectangle([x, y, x + bw, y + bh], radius=bh // 2, fill=_hex(pal["accent"]))
    d.text((x + pad_x, y + pad_y - int(size * 0.08)), text, font=f, fill=(255, 255, 255, 255))


_LAYOUTS = {
    "bottom_band": _layout_bottom_band,
    "top_bottom": _layout_top_bottom,
    "side_panel": _layout_side_panel,
    "list_grid": _layout_list_grid,
}


# ──────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────

def render(
    background: Image.Image,
    fmt: dict,
    style: dict,
    headline: str,
    sub: str = "",
    items: list[dict] | None = None,
    badge: str = "",
) -> Image.Image:
    """배경 이미지 위에 문구·가격·뱃지를 규격에 맞춰 배치한다.

    background 는 '글자 없는 배경'이어야 한다 (image_gen 이 생성).
    """
    size = tuple(fmt["size"])
    canvas = _cover(background.convert("RGBA"), size)
    fn = _LAYOUTS[fmt["layout"]]
    return fn(canvas, fmt, style, headline.strip(), sub.strip(), items or [], badge.strip())


def to_png_bytes(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
