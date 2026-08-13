"""포스터 부품 테스트 — 글꼴이 없는 환경(CI)에서도 돌도록 기본 글꼴로 바꿔치기한다."""

import pytest
from PIL import Image, ImageFont

from app_core import fonts, poster


def _fake_font(role: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)


def test_paper_background():
    bg = poster.paper_background(size=128)
    assert bg.size == (128, 128)
    assert bg.mode == "RGB"


def test_generate_poster_full(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    product = Image.new("RGBA", (60, 40), (255, 0, 0, 255))
    ad = poster.generate_poster(
        product,
        "가게이름",
        tagline="태그라인",
        badge="신규 오픈",
        date_line="3월",
        features=["제목|설명", "둘|설명", "셋|설명"],
        event="이벤트",
        headline="헤드라인",
        info="주소 · 시간",
        palette="soft_pink",
    )
    assert ad.size == (1080, 1080)
    assert ad.mode == "RGB"


def test_generate_poster_minimal(monkeypatch):
    """빈 블록은 그리지 않는다 — 없는 정보를 지어내지 않기 위해서다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    ad = poster.generate_poster(None, "가게이름")
    assert ad.mode == "RGB"


def test_unknown_palette_is_rejected(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    with pytest.raises(ValueError):
        poster.generate_poster(None, "가게", palette="노랑무지개")
