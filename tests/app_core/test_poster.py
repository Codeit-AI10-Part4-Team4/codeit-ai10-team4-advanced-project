"""포스터 부품 테스트 — 글꼴이 없는 환경(CI)에서도 돌도록 기본 글꼴로 바꿔치기한다."""

import pytest
from PIL import Image, ImageFont

from app_core import fonts, poster


def _fake_font(role: str, size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)


def test_paper_background():
    bg = poster.paper_background(size=128)
    assert bg.size == (128, 128)
    assert bg.mode == "RGB"


def test_큰_가격칸과_문구에_같은_가격을_중복하지_않는다():
    assert poster._without_repeated_price("여름 세트 · 6,500원", "6,500원") == "여름 세트"
    assert poster._without_repeated_price("여름 세트 6500원", "6,500원") == "여름 세트"


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
        product_name="대표 상품",
        sub="상품 설명",
        price_text="19,900원",
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


def test_업로드_포스터는_누끼가_아닌_사진_전체를_카드에_맞춘다(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    source = Image.new("RGB", (100, 60), (10, 20, 30))
    source.paste((200, 10, 10), (0, 0, 20, 20))
    seen = {}

    def _fit(photo, size):
        seen["same"] = photo.tobytes() == source.tobytes()
        seen["size"] = size
        return Image.new("RGB", size, (40, 50, 60))

    monkeypatch.setattr(poster, "fit_photo_canvas", _fit)
    ad = poster.generate_uploaded_photo_poster(
        source,
        "가게이름",
        headline="선택한 문구",
        product_name="대표 상품",
        sub="상품 설명",
        price_text="19,900원",
        info="서울 마포구",
    )

    assert seen == {"same": True, "size": (760, 506)}
    assert ad.size == (1080, 1080)
    assert ad.mode == "RGB"


def test_사진_유무와_상관없이_같은_크기의_중앙_카드를_쓴다(monkeypatch):
    """두 포스터가 서로 다른 디자인으로 갈라지지 않도록 공통 카드 계약을 고정한다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    seen: list[tuple[int, int]] = []

    def _fit(photo, size):
        seen.append(size)
        return Image.new("RGB", size, (40, 50, 60))

    monkeypatch.setattr(poster, "fit_photo_canvas", _fit)
    photo = Image.new("RGB", (120, 80), (10, 20, 30))

    poster.generate_uploaded_photo_poster(photo, "가게", headline="문구")
    poster.generate_poster(photo, "가게", headline="문구")

    assert seen == [(760, 506), (760, 506)]


def test_unknown_palette_is_rejected(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    with pytest.raises(ValueError):
        poster.generate_poster(None, "가게", palette="노랑무지개")
