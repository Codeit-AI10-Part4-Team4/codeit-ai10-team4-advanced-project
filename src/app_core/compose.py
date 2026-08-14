"""광고 조립 부품 ─ 배경 생성 + 제품 합성 + 문구 오버레이 (실험 근거: notebooks/pipeline_v0.ipynb)"""

from PIL import Image, ImageDraw

# 글꼴 후보는 `fonts.py` 한 곳에서만 관리한다. 여기 따로 두면 새 OS 를 지원할 때
# 한쪽만 고치게 되고, 그 한쪽은 반드시 잊힌다.
from app_core import fonts


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
    product: Image.Image | None,
    headline: str,
    sub: str = "",
    size: tuple[int, int] = (1080, 1080),
    background: Image.Image | None = None,
) -> Image.Image:
    """누끼 딴 제품 이미지를 배경 위에 얹고 문구를 그려 광고 이미지를 만든다.

    headline·sub는 문구 생성이 주는 형식(CopyCandidate) 그대로다 —
    헤드라인은 크게, 서브는 그 아래 작게. 가격은 보통 sub에 녹아 온다.
    background를 주면 크기를 맞춰 배경으로 쓰고, 없으면 그라데이션(임시)을 깐다.
    product가 None이면 사진 없이 배경과 문구만으로 만든다(텍스트 광고).
    """
    w, h = size
    bg = background.resize(size) if background else make_gradient_background(size)
    canvas = bg.convert("RGBA")

    if product is not None:
        # 투명 여백을 잘라 제품이 크게 보이게 (개선 1호)
        bbox = product.getbbox()
        prod = product.crop(bbox) if bbox else product.copy()
        prod.thumbnail((int(w * 0.75), int(h * 0.62)))
        canvas.alpha_composite(prod, ((w - prod.width) // 2, h - prod.height - 100))

    # 사진이 없으면 위쪽이 허전하므로 문구를 가운데로 내린다.
    head_y = 140 if product is not None else int(h * 0.42)

    d = ImageDraw.Draw(canvas)
    max_text_w = int(w * 0.9)
    head_font = fonts.fit(headline, max_text_w, 76, floor=30)
    d.text(
        (w // 2, head_y),
        headline,
        font=head_font,
        fill=(255, 255, 255),
        anchor="mm",
        stroke_width=4,
        stroke_fill=(60, 35, 15),
    )
    if sub:
        sub_font = fonts.fit(sub, max_text_w, 52, floor=30)
        d.text(
            (w // 2, head_y + 95),
            sub,
            font=sub_font,
            fill=(255, 245, 230),
            anchor="mm",
            stroke_width=3,
            stroke_fill=(60, 35, 15),
        )

    return canvas.convert("RGB")
