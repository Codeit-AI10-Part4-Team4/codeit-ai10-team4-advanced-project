"""광고 조립 부품 v2 ─ 배경 위에 제품·문구를 레퍼런스 규칙대로 얹는다.

규칙 근거: 문서/compose_v2_규칙명세.md (인스타 카페 광고 18장 분석, 2026-08-15)
  - 글자는 상단 1/3 또는 하단 1/3 (레퍼런스 13/18) — 중앙 박치기 금지
  - 모든 문구 두꺼운 외곽선 일괄 적용 0/18 → stroke 제거, 배경 대비색 또는 그라데이션 판
  - 폰트 역할 2종(display 제목 + body_light 부제), 디자인 색 3색 이내
  - 제품(cutout)은 글자 아래 '사용 가능 상자' 안에 축소, 바닥 그림자

입력 계약(pipeline.py): product 가 있으면 cutout(누끼 레이어), 없으면 keep/hero/generate —
compose 는 뒤 셋을 구분하지 못하므로 product 유무 두 갈래로만 동작한다.
"""

import logging
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat

# 글꼴 후보는 `fonts.py` 한 곳에서만 관리한다. 여기 따로 두면 새 OS 를 지원할 때
# 한쪽만 고치게 되고, 그 한쪽은 반드시 잊힌다.
from app_core import fonts
from app_core.photo_enhance import fit_photo_canvas

Zone = Literal["top", "bottom"]

# ── 비율 규칙 (명세 §2) — 전부 캔버스 비율이라 1080 외 크기에도 그대로 ─────
_MARGIN_X = 0.07  #: 좌우 안전 여백
_ZONE_H = 0.33  #: 글자 영역 높이 (상단 또는 하단 1/3)
_HEAD_TOP = 0.08  #: 상단형 제목 시작 y
_HEAD_BOTTOM_START = 0.72  #: 하단형 제목 시작 y
_HEAD_SIZE = 0.085  #: 제목 시작 크기 (캔버스 폭 비율)
_HEAD_FLOOR = 0.055  #: 제목 하한
_SUB_RATIO = 0.42  #: 부제 = 제목 × 0.42
_LINE_GAP = 0.35  #: 제목·부제 간격 = 제목 글자 높이 × 0.35
_MAX_LINES = 2
_PRODUCT_GAP = 0.03  #: 글자 영역과 제품 사이
_PRODUCT_BOTTOM = 0.08  #: 제품 하단 여백
#: 글자 영역 밝기 std 가 이보다 크면 그라데이션 판. 55 로 시작했다가 실제 생성 배경에서
#: std 50.5·53.5 인 사례(꽃집)가 안 읽혀 50 으로 보정 — 코드 밖 자료 없이 이 숫자만 근거.
_STD_THRESHOLD = 50.0
_PANEL_ALPHA = 0.55  #: 판 최대 불투명도
_PANEL_EXTRA = 0.06  #: 판 높이 = 글자 영역 + 6%
_SHADOW_ALPHA = 0.25
_SHADOW_BLUR = 0.022  #: 그림자 흐림 반경 = 캔버스 높이 비율 (1080 기준 24px)

_DARK = (26, 26, 26)  #: 밝은 배경 위 글자
_LIGHT = (250, 250, 250)  #: 어두운 배경 위 글자
_log = logging.getLogger(__name__)

# ── 연출 표기 (README §생성 모드 · docs/01 §생성 모드) ────────────
# 제품 사진 없이 만든 광고는 **상품 이미지를 AI 가 그린 것**이라 사장님의 실제
# 상품이 아니다. 표기가 없으면 사장님이 그 그림을 자기 상품 사진인 양 올리게 된다.
#
# **화면 캡션이 아니라 이미지에 새긴다.** 사장님은 이 PNG 를 받아 인스타에 올리는데
# Streamlit 캡션은 거기까지 따라가지 않는다. 표기가 붙어 있어야 할 곳은 이미지다.
STAGED_NOTICE = "연출된 이미지"
_NOTICE_SIZE = 0.024  #: 캔버스 폭 비율 (1080 → 25px)
_NOTICE_MARGIN = 0.025
_NOTICE_PAD = 0.013
_NOTICE_BG = (0, 0, 0, 130)
_NOTICE_FG = (255, 255, 255, 235)

# 사장님이 올린 사진은 상품을 다시 배치하지 않고 사진 자체가 화면의 주인공이 된다.
# 생성 배경/누끼 조판과 같은 큰 중앙 제목을 쓰면 상품을 가리므로 별도 계약으로 둔다.
_PHOTO_PANEL_H = 0.37
_PHOTO_PANEL_ALPHA = 170
_PHOTO_X = 0.067
_PHOTO_HEAD_SIZE = 0.058
_PHOTO_HEAD_FLOOR = 0.041
_PHOTO_SUB_SIZE = 0.028
_PHOTO_WARM_WHITE = (250, 248, 244)
_PHOTO_ACCENT = (245, 194, 105)


def draw_staged_notice(canvas: Image.Image, corner: Zone = "bottom") -> None:
    """ "연출된 이미지" 를 이미지 구석에 새긴다. `corner` 는 글자 영역의 **반대쪽**.

    왼쪽에 붙이는 이유: 두 조판 모두 가운데(문구·정보 줄)와 오른쪽(제품·배지)을
    쓴다. 왼쪽 구석이 양쪽 다 가장 한산하다.

    어떤 배경에도 읽히도록 반투명 판을 깔고 흰 글자를 얹는다. 무엇과 겹치더라도
    읽히는 쪽이 맞다 — **안 보이는 표기는 표기가 아니다.**
    """
    w, h = canvas.size
    font = fonts.load("body_light", max(12, int(w * _NOTICE_SIZE)))
    pad, margin = int(w * _NOTICE_PAD), int(w * _NOTICE_MARGIN)

    draw = ImageDraw.Draw(canvas, "RGBA")
    text_w = int(draw.textlength(STAGED_NOTICE, font=font))
    text_h = sum(font.getmetrics())

    x0 = margin
    y0 = margin if corner == "top" else h - margin - text_h - pad * 2
    box = (x0, y0, x0 + text_w + pad * 2, y0 + text_h + pad * 2)

    draw.rounded_rectangle(box, radius=int(pad * 1.5), fill=_NOTICE_BG)
    draw.text((x0 + pad, y0 + pad), STAGED_NOTICE, font=font, fill=_NOTICE_FG)


def make_gradient_background(
    size: tuple[int, int] = (1080, 1080),
    top: tuple[int, int, int] = (255, 244, 228),
    bottom: tuple[int, int, int] = (240, 160, 90),
) -> Image.Image:
    """세로 그라데이션 배경을 만든다. (임시 부품 ─ 추후 SDXL 생성 배경으로 교체)"""
    w, h = size
    bg = Image.new("RGB", size)
    d = ImageDraw.Draw(bg)
    for y in range(h):
        t = y / h
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=color)
    return bg


# ── 분석 ─────────────────────────────────────────────────────


def zone_box(size: tuple[int, int], zone: Zone) -> tuple[int, int, int, int]:
    """글자 영역 사각형 — 좌우 7% 제외, 상단 또는 하단 33%."""
    w, h = size
    x0, x1 = int(w * _MARGIN_X), int(w * (1 - _MARGIN_X))
    if zone == "top":
        return (x0, 0, x1, int(h * _ZONE_H))
    return (x0, int(h * (1 - _ZONE_H)), x1, h)


def zone_stats(bg: Image.Image, zone: Zone) -> tuple[float, float]:
    """글자 영역의 밝기 (평균, 표준편차). 표준편차가 곧 '복잡도'다."""
    g = ImageOps.grayscale(bg).crop(zone_box(bg.size, zone))
    s = ImageStat.Stat(g)
    return s.mean[0], s.stddev[0]


def pick_zone(bg: Image.Image, product: Image.Image | None) -> Zone:
    """글자를 어디 둘지 — 제품(누끼)이 있으면 상단 고정, 없으면 덜 복잡한 쪽."""
    if product is not None:
        return "top"
    _, top_std = zone_stats(bg, "top")
    _, bottom_std = zone_stats(bg, "bottom")
    return "top" if top_std <= bottom_std else "bottom"


# ── 글자 ─────────────────────────────────────────────────────


def wrap_to_fit(text: str, max_width: int, role: str, start: int, floor: int) -> tuple:
    """폭에 맞게 크기를 줄이고, 그래도 안 되면 최대 2줄, 그래도 넘치면 말줄임.

    반환: (font, lines)
    """
    font = fonts.fit(text, max_width, start, role, floor=floor)
    if font.getlength(text) <= max_width:
        return font, [text]

    font = fonts.load(role, floor)
    words = text.split()
    if len(words) >= 2:
        # 공백 기준으로 두 줄 — 앞줄이 폭 안에 들어가는 가장 긴 분할
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            if font.getlength(a) <= max_width:
                best = (a, b)
        lines = list(best) if best else [words[0], " ".join(words[1:])]
    else:
        half = max(1, len(text) // 2)
        lines = [text[:half], text[half:]]

    return font, [_ellipsize(line, font, max_width) for line in lines[:_MAX_LINES]]


def _ellipsize(line: str, font, max_width: int) -> str:
    if font.getlength(line) <= max_width:
        return line
    original = line
    while line and font.getlength(line + "…") > max_width:
        line = line[:-1]
    _log.info("문구가 폭을 넘어 말줄임: %r → %r", original, line + "…")
    return line + "…"


def _text_color(bg: Image.Image, zone: Zone) -> tuple[int, int, int]:
    mean, _ = zone_stats(bg, zone)
    return _DARK if mean > 128 else _LIGHT


def _draw_panel(canvas: Image.Image, zone: Zone) -> None:
    """글자 영역 뒤 검정 그라데이션 판 — 상단형은 위가 진하고, 하단형은 아래가 진하다."""
    w, h = canvas.size
    ph = int(h * (_ZONE_H + _PANEL_EXTRA))
    panel = Image.new("RGBA", (w, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    for y in range(ph):
        t = y / ph  # 0(위) → 1(아래)
        a = (1 - t) if zone == "top" else t
        d.line([(0, y), (w, y)], fill=(0, 0, 0, int(255 * _PANEL_ALPHA * a)))
    canvas.alpha_composite(panel, (0, 0 if zone == "top" else h - ph))


def _draw_preserved_photo_text(
    canvas: Image.Image,
    shop: str,
    headline: str,
    sub: str,
) -> int:
    """실사진 위에 작은 좌측 정렬 문구를 그린다.

    사진의 상품 픽셀을 살리는 경로다. 항상 같은 상단 그라데이션과 따뜻한 흰색을
    사용해 사진마다 조판이 요동하지 않으며, 중앙 제품 영역을 비워 둔다.
    """
    w, h = canvas.size
    panel_h = max(1, int(h * _PHOTO_PANEL_H))
    panel = Image.new("RGBA", (w, panel_h), (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    for py in range(panel_h):
        ratio = py / max(1, panel_h - 1)
        alpha = int(_PHOTO_PANEL_ALPHA * (1 - ratio) ** 0.8)
        panel_draw.line((0, py, w, py), fill=(11, 13, 16, alpha))
    canvas.alpha_composite(panel, (0, 0))

    d = ImageDraw.Draw(canvas, "RGBA")
    x = int(w * _PHOTO_X)
    max_w = int(w * (1 - _PHOTO_X * 2))
    y = int(h * 0.057)

    if shop:
        shop_font = fonts.fit(
            shop,
            max_w,
            max(12, int(w * 0.027)),
            "body_light",
            floor=max(11, int(w * 0.020)),
        )
        text_h = sum(shop_font.getmetrics())
        pad_x = max(8, int(w * 0.016))
        pad_y = max(5, int(h * 0.008))
        pill_w = int(shop_font.getlength(shop)) + pad_x * 2
        pill_h = text_h + pad_y * 2
        d.rounded_rectangle(
            (x, y, x + pill_w, y + pill_h),
            radius=pill_h // 2,
            fill=(0, 0, 0, 112),
        )
        d.text(
            (x + pad_x, y + pill_h // 2),
            shop,
            font=shop_font,
            fill=(*_PHOTO_WARM_WHITE, 255),
            anchor="lm",
        )
        y += pill_h + int(h * 0.027)

    head_font, head_lines = wrap_to_fit(
        headline,
        max_w,
        "body",
        max(20, int(w * _PHOTO_HEAD_SIZE)),
        max(16, int(w * _PHOTO_HEAD_FLOOR)),
    )
    shadow_offset = max(1, int(w * 0.002))
    head_h = sum(head_font.getmetrics())
    for line in head_lines:
        d.text(
            (x + shadow_offset, y + shadow_offset),
            line,
            font=head_font,
            fill=(0, 0, 0, 105),
        )
        d.text((x, y), line, font=head_font, fill=(*_PHOTO_WARM_WHITE, 255))
        y += head_h

    y += max(7, int(h * 0.010))
    d.rounded_rectangle(
        (x, y, x + int(w * 0.070), y + max(3, int(h * 0.004))),
        radius=2,
        fill=(*_PHOTO_ACCENT, 255),
    )
    y += max(16, int(h * 0.028))

    if sub:
        sub_start = max(14, int(w * _PHOTO_SUB_SIZE))
        sub_font, sub_lines = wrap_to_fit(
            sub,
            max_w,
            "body_light",
            sub_start,
            max(12, int(w * 0.021)),
        )
        sub_h = sum(sub_font.getmetrics())
        for line in sub_lines:
            d.text(
                (x + shadow_offset, y + shadow_offset),
                line,
                font=sub_font,
                fill=(0, 0, 0, 105),
            )
            d.text((x, y), line, font=sub_font, fill=(*_PHOTO_WARM_WHITE, 245))
            y += sub_h
    return y


def _draw_text(canvas: Image.Image, bg: Image.Image, zone: Zone, headline: str, sub: str) -> int:
    """제목·부제를 글자 영역에 그린다. 반환: 글자 블록의 마지막 y (제품 상자 계산용)."""
    w, h = canvas.size
    x0, _, x1, _ = zone_box(canvas.size, zone)
    max_w = x1 - x0

    _, std = zone_stats(bg, zone)
    if std > _STD_THRESHOLD:
        _draw_panel(canvas, zone)
        color = _LIGHT
    else:
        color = _text_color(bg, zone)

    head_font, head_lines = wrap_to_fit(
        headline, max_w, "display", int(w * _HEAD_SIZE), int(w * _HEAD_FLOOR)
    )
    # 줄 advance 는 em(font.size) 이 아니라 asc+desc 다. em 을 쓰면 2줄 제목에서
    # 아랫줄이 윗줄에 달라붙는다 — display 91px 기준 잉크 간격이 4px 밖에 안 남는다.
    head_h = sum(head_font.getmetrics())
    sub_font, sub_lines = (None, [])
    if sub:
        sub_start = int(head_font.size * _SUB_RATIO)
        sub_font, sub_lines = wrap_to_fit(
            sub, max_w, "body_light", sub_start, max(12, sub_start // 2)
        )

    # 블록 총 높이 — 33% 를 넘으면 부제를 1줄 말줄임으로
    gap = int(head_h * _LINE_GAP)
    block_h = head_h * len(head_lines)
    if sub_font is not None:
        block_h += gap + sub_font.size * len(sub_lines)
    if sub_font is not None and block_h > h * _ZONE_H:
        sub_lines = [_ellipsize(" ".join(sub_lines), sub_font, max_w)]

    y = int(h * (_HEAD_TOP if zone == "top" else _HEAD_BOTTOM_START))
    d = ImageDraw.Draw(canvas)
    for line in head_lines:
        d.text((w // 2, y), line, font=head_font, fill=color, anchor="ma")
        y += head_h
    if sub_lines and sub_font is not None:
        y += gap
        for line in sub_lines:
            d.text((w // 2, y), line, font=sub_font, fill=color, anchor="ma")
            y += sub_font.size
    return y


# ── 제품 ─────────────────────────────────────────────────────


def _place_product(canvas: Image.Image, product: Image.Image, text_bottom: int) -> None:
    """제품을 '사용 가능 상자'(글자 아래 3% ~ 하단 8%) 안에 축소해 넣고 바닥 그림자를 깐다."""
    w, h = canvas.size
    blur = max(2, int(h * _SHADOW_BLUR))
    x0, x1 = int(w * _MARGIN_X), int(w * (1 - _MARGIN_X))
    y0 = text_bottom + int(h * _PRODUCT_GAP)
    y1 = int(h * (1 - _PRODUCT_BOTTOM))
    if y1 - y0 < h * 0.1:  # 상자가 너무 작으면 그리지 않는 것보다 최소한은 보이게
        y0 = y1 - int(h * 0.1)

    bbox = product.getbbox()
    prod = product.crop(bbox) if bbox else product.copy()
    prod.thumbnail((x1 - x0, y1 - y0))
    px = (w - prod.width) // 2
    py = y1 - prod.height

    # 바닥 그림자 — 제품 아래 납작한 타원, 제품보다 먼저 그려서 뒤에 깔린다
    sw, sh = int(prod.width * 0.9), max(4, int(prod.height * 0.06))
    shadow = Image.new("RGBA", (sw + blur * 4, sh + blur * 4), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        [blur * 2, blur * 2, blur * 2 + sw, blur * 2 + sh],
        fill=(0, 0, 0, int(255 * _SHADOW_ALPHA)),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(shadow, ((w - shadow.width) // 2, py + prod.height - sh // 2 - blur * 2))
    canvas.alpha_composite(prod, (px, py))


# ── 조립 ─────────────────────────────────────────────────────


def compose_ad(
    product: Image.Image | None,
    headline: str,
    sub: str = "",
    size: tuple[int, int] = (1080, 1080),
    background: Image.Image | None = None,
    staged: bool = False,
    shop: str = "",
    preserved_photo: bool = False,
) -> Image.Image:
    """배경 위에 문구(와 제품)를 레퍼런스 규칙대로 얹어 광고 이미지를 만든다.

    headline·sub 는 문구 생성이 주는 형식(CopyCandidate) 그대로다.
    background 를 주면 크기를 맞춰 쓰고, 없으면 그라데이션(임시)을 깐다.
    product 가 있으면(cutout) 글자는 상단, 제품은 그 아래 상자에. 없으면 글자만 —
    상단·하단 중 덜 복잡한 쪽에.

    `staged` 는 **상품 이미지를 AI 가 그렸는지**다. 부르는 쪽(pipeline)이 정해서 준다 —
    위 입력 계약대로 compose 는 안전 보정 실사진과 hero/generate(AI 그림)를 구분하지
    못한다. `product is None` 으로 짐작하면 **사장님이 찍은 진짜 사진에 연출 딱지**가 붙는다.
    """
    bg = (
        fit_photo_canvas(background, size) if background else make_gradient_background(size)
    ).convert("RGB")
    canvas = bg.convert("RGBA")

    if preserved_photo:
        zone: Zone = "top"
        text_bottom = _draw_preserved_photo_text(canvas, shop, headline, sub)
    else:
        zone = pick_zone(bg, product)
        text_bottom = _draw_text(canvas, bg, zone, headline, sub)
    if product is not None:
        _place_product(canvas, product, text_bottom)
    if staged:
        # 글자 영역 반대쪽 — 문구를 가리지 않는다
        draw_staged_notice(canvas, "bottom" if zone == "top" else "top")

    return canvas.convert("RGB")
