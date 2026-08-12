"""포스터 부품 테스트 — 글꼴이 없는 환경(CI)에서도 돌도록 기본 글꼴로 바꿔치기한다."""

from PIL import Image, ImageFont

from app_core import fonts, poster


def _fake_font(role: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)


def test_paper_background():
    bg = poster.paper_background(size=128)
    assert bg.size == (128, 128)
    assert bg.mode == "RGB"


def test_generate_poster_with_product(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    product = Image.new("RGBA", (60, 40), (255, 0, 0, 255))
    ad = poster.generate_poster(product, "가게이름", "헤드라인", sub="서브", badge="OPEN")
    assert ad.size == (1080, 1080)
    assert ad.mode == "RGB"


def test_generate_poster_without_product(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    ad = poster.generate_poster(None, "가게이름", "헤드라인", tagline="태그", event="이벤트\n무료")
    assert ad.mode == "RGB"
