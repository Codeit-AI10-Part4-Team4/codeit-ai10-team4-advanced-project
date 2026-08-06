"""광고 조립 부품 ─ 배경 생성 + 제품 합성 + 문구 오버레이 (실험 근거: notebooks/pipeline_v0.ipynb)"""

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgunbd.ttf",  # 윈도우
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",  # 리눅스
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """OS마다 다른 한글 폰트 경로를 순서대로 시도한다."""
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise OSError("한글 폰트를 찾지 못했습니다. _FONT_CANDIDATES에 경로를 추가하세요.")


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


def compose_ad(
    product: Image.Image,
    headline: str,
    price: str | None = None,
    size: tuple[int, int] = (1080, 1080),
) -> Image.Image:
    """누끼 딴 제품 이미지를 배경 위에 얹고 문구를 그려 광고 이미지를 만든다."""
    w, h = size
    canvas = make_gradient_background(size).convert("RGBA")

    # 투명 여백을 잘라 제품이 크게 보이게 (개선 1호)
    bbox = product.getbbox()
    prod = product.crop(bbox) if bbox else product.copy()
    prod.thumbnail((int(w * 0.75), int(h * 0.62)))
    canvas.alpha_composite(prod, ((w - prod.width) // 2, h - prod.height - 100))

    d = ImageDraw.Draw(canvas)
    d.text((w // 2, 140), headline, font=_load_font(76), fill=(70, 45, 20), anchor="mm")
    if price:
        d.text((w // 2, 235), price, font=_load_font(52), fill=(210, 85, 20), anchor="mm")

    return canvas.convert("RGB")
