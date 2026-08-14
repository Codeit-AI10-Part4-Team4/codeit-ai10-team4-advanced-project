"""compose 부품 테스트 — 폰트·GPU 없이 돌도록 작은 이미지와 기본 폰트를 쓴다."""

from PIL import Image, ImageFont

from app_core import compose, fonts


def _fake_font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """글꼴 선택은 `fonts` 한 곳에서만 한다 — 대역도 거기에 세운다."""
    return ImageFont.load_default(size)


def test_gradient_background_size_and_mode():
    bg = compose.make_gradient_background(size=(64, 64))
    assert bg.size == (64, 64)
    assert bg.mode == "RGB"
    assert bg.getpixel((0, 0)) == (255, 244, 228)


def test_compose_ad_returns_rgb_canvas(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    product = Image.new("RGBA", (40, 30), (255, 0, 0, 255))
    ad = compose.compose_ad(product, "헤드라인", "서브 문구", size=(256, 256))
    assert ad.size == (256, 256)
    assert ad.mode == "RGB"


def test_compose_ad_uses_given_background(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    product = Image.new("RGBA", (40, 30), (255, 0, 0, 255))
    blue = Image.new("RGB", (64, 64), (0, 0, 255))
    ad = compose.compose_ad(product, "제목", size=(256, 256), background=blue)
    assert ad.getpixel((5, 250)) == (0, 0, 255)


def test_compose_ad_without_product(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    ad = compose.compose_ad(None, "사진 없는 광고", "문구만으로", size=(256, 256))
    assert ad.size == (256, 256)
    assert ad.mode == "RGB"
