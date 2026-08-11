"""이미지 생성 — 현재는 스텁.

모델이 아직 미정이라 실제 Diffusion 파이프라인 대신 색보정 기반 스텁으로 동작한다.
전체 UX 흐름과 레이아웃 엔진을 먼저 검증하는 것이 목적.

━━ 생성 모드 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사용자는 모드를 고르지 않는다. 무엇을 올렸는지로 자동 결정된다.

  제품사진  레퍼런스   모드            프로젝트 요구사항 대응
  ────────────────────────────────────────────────────────────
     O         X      preserve        광고 이미지 3 (입력 이미지 보존)
     O         O      preserve_ref    광고 이미지 2 + 3
     X         O      reference       광고 이미지 2 (레퍼런스 사용)
     X         X      scene           광고 이미지 1 (텍스트 입력만)

━━ 실제 모델로 교체할 지점 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
generate() 내부만 갈아끼우면 된다. 호출부(app.py)는 바뀌지 않는다.
넷 다 SDXL 하나 위에서 conditioning 만 다르므로 모델은 한 번만 올린다.

  preserve      누끼(rembg/SAM) → SDXL Inpainting 또는 ControlNet(depth)
  preserve_ref  위 + IP-Adapter (레퍼런스에서 분위기·색조만 차용)
  reference     SDXL + IP-Adapter
  scene         SDXL text-to-image
                실제 제품을 사칭하지 않으므로 이 경우에만 t2i 가 정당하다

build_prompt() 가 만든 프롬프트를 그대로 사용하면 된다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

NEGATIVE_PROMPT = "text, letters, watermark, logo, people, hands, blurry, distorted"

MODE_LABEL = {
    "preserve": "제품 보존 — 제품은 그대로 두고 배경·조명만 교체합니다",
    "preserve_ref": "제품 보존 + 레퍼런스 — 제품은 그대로, 분위기는 레퍼런스에서 가져옵니다",
    "reference": "레퍼런스 기반 — 올려주신 이미지의 분위기로 배경을 만듭니다",
    "scene": "텍스트 기반 — 요청하신 내용으로 배경을 만듭니다",
}

MODE_REQUIREMENT = {
    "preserve": "광고 이미지 3 (입력 이미지 보존)",
    "preserve_ref": "광고 이미지 2 + 3",
    "reference": "광고 이미지 2 (레퍼런스 사용)",
    "scene": "광고 이미지 1 (텍스트 입력만)",
}


def resolve_mode(photo: Image.Image | None, reference: Image.Image | None) -> str:
    """무엇을 올렸는지로 생성 모드를 결정한다. 사용자는 모드를 고르지 않는다."""
    if photo is not None:
        return "preserve_ref" if reference is not None else "preserve"
    return "reference" if reference is not None else "scene"


def build_prompt(
    industry: dict,
    style: dict,
    mode: str = "preserve",
    caption: str = "",
    request: str = "",
) -> str:
    """실제 Diffusion 모델에 보낼 프롬프트.

    사용자는 프롬프트를 쓰지 않는다. 업종 × 스타일 × (VLM 캡션) 을
    서비스가 조합해서 만든다. — docs/01 7장 'VLM 을 넣는 이유'
    `request` 는 고급 옵션에서 사장님이 직접 덧붙인 요청사항.
    """
    parts = [caption or industry.get("label", ""), industry["scene_prompt"], style["prompt_suffix"]]
    if request:
        parts.append(request)
    if mode in ("preserve", "preserve_ref"):
        parts.append("product stays unchanged, background only")
    if mode in ("reference", "preserve_ref"):
        parts.append("[IP-Adapter: 레퍼런스 이미지에서 분위기·색조 차용]")
    return ", ".join(p for p in parts if p)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _dominant(img: Image.Image) -> tuple[int, int, int]:
    """레퍼런스 이미지의 대표 색. 스텁에서 '분위기 차용'을 흉내내는 데 쓴다."""
    small = img.convert("RGB").resize((32, 32), Image.LANCZOS)
    pixels = list(small.getdata())
    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    return (r, g, b)


def _grade(img: Image.Image, style: dict, tint_rgb: tuple[int, int, int] | None = None,
           tint_alpha: float | None = None) -> Image.Image:
    """스타일 팔레트(또는 레퍼런스 색) 방향으로 색보정 — 조명·톤 교체를 흉내낸다."""
    g = style.get("grade", {})
    img = ImageEnhance.Brightness(img).enhance(g.get("brightness", 1.0))
    img = ImageEnhance.Contrast(img).enhance(g.get("contrast", 1.0))
    img = ImageEnhance.Color(img).enhance(g.get("saturation", 1.0))

    rgb = tint_rgb or (_hex(g["tint"]) if g.get("tint") else None)
    if rgb:
        alpha = tint_alpha if tint_alpha is not None else g.get("tint_alpha", 0.08)
        tint = Image.new("RGB", img.size, rgb)
        img = Image.blend(img.convert("RGB"), tint, alpha)
    return img


def _vignette(img: Image.Image, strength: float = 0.35) -> Image.Image:
    """가장자리를 살짝 눌러 제품에 시선이 모이게 한다."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w * 0.25, -h * 0.25, w * 1.25, h * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) * 0.12))
    dark = ImageEnhance.Brightness(img).enhance(1 - strength)
    return Image.composite(img.convert("RGB"), dark, mask)


def _scene(size: tuple[int, int], style: dict, seed: int,
           base_rgb: tuple[int, int, int] | None = None) -> Image.Image:
    """사진 소재가 없을 때 — 배경만 생성.

    base_rgb 가 주어지면 레퍼런스 이미지의 색을 기반으로 만든다 (reference 모드).
    """
    w, h = size
    rnd = random.Random(seed)
    bg = base_rgb or _hex(style["palette"]["bg"])
    accent = _hex(style["palette"]["accent"])
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(5):
        r = rnd.uniform(0.25, 0.6) * max(w, h)
        cx, cy = rnd.uniform(0, w), rnd.uniform(0, h)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*accent, rnd.randint(18, 46)))
    return img.filter(ImageFilter.GaussianBlur(max(w, h) * 0.06))


def generate(
    photo: Image.Image | None,
    industry: dict,
    style: dict,
    size: tuple[int, int],
    seed: int = 0,
    reference: Image.Image | None = None,
) -> Image.Image:
    """광고 배경 이미지를 만든다. 글자는 넣지 않는다 (layout.render 담당).

    Returns: RGB 이미지 (캔버스 크기로 맞추는 것은 layout 이 처리)
    """
    mode = resolve_mode(photo, reference)
    ref_rgb = _dominant(reference) if reference is not None else None

    if photo is None:
        return _scene(size, style, seed, base_rgb=ref_rgb)

    img = photo.convert("RGB")
    if ref_rgb is not None:
        # preserve_ref — 레퍼런스의 색조를 배경 톤에 반영 (실제로는 IP-Adapter 역할)
        img = _grade(img, style, tint_rgb=ref_rgb, tint_alpha=0.16)
    else:
        img = _grade(img, style)
    return _vignette(img, 0.28 + (seed % 3) * 0.06)   # seed 로 3안에 미묘한 차이
