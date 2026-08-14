"""조립 부품 테스트 — 무거운 부품(확산 모델·LLM·누끼)은 대역으로 바꾼다."""

from PIL import Image, ImageFont

from app_core import compose, fonts, pipeline
from app_core.poster_plan import PosterPlan
from app_core.schema import AdBrief, CopyCandidate, Store


def _fake_font(role: str, size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)


def _store() -> Store:
    return Store(
        id=1, user_id=1, industry="cafe", name="연남 크로플", address="서울시 마포구 연남동"
    )


def _brief() -> AdBrief:
    return AdBrief(goal="image", product="크로플", price=4500, situation="신메뉴")


def test_poster_style_uses_plan(monkeypatch):
    """포스터 형태는 기획 부품이 채운 내용으로 그린다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero prompt")
    monkeypatch.setattr(
        pipeline,
        "generate_background",
        lambda prompt: Image.new("RGB", (512, 512), (200, 180, 160)),
    )
    monkeypatch.setattr(
        pipeline,
        "plan_poster",
        lambda **kwargs: PosterPlan(
            tagline="동네 크로플",
            badge="신메뉴",
            date_line="",
            features=["바삭함|겉은 바삭 속은 촉촉"],
            event="",
            palette="warm_bakery",
        ),
    )
    ad = pipeline.generate_ad(
        _brief(), _store(), CopyCandidate(headline="크로플 나왔어요"), "poster"
    )
    assert ad.size == (1080, 1080)
    assert ad.mode == "RGB"


def test_simple_style_uses_generated_background(monkeypatch):
    """심플 형태는 배경을 생성해 그 위에 얹는다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        pipeline, "generate_background", lambda prompt: Image.new("RGB", (1080, 1080), (10, 20, 30))
    )
    monkeypatch.setattr(compose, "_load_font", lambda size: ImageFont.load_default(size))
    ad = pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")
    assert ad.size == (1080, 1080)


def test_poster_style_without_photo_generates_hero(monkeypatch):
    """사진이 없으면 주인공 이미지를 생성해 채운다 — 오른쪽이 비면 안 된다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero prompt")
    monkeypatch.setattr(
        pipeline,
        "generate_background",
        lambda prompt: Image.new("RGB", (512, 512), (200, 180, 160)),
    )
    monkeypatch.setattr(
        pipeline,
        "plan_poster",
        lambda **kwargs: PosterPlan(
            tagline="t", badge="b", date_line="", features=["a|b"], event="", palette="fresh_mint"
        ),
    )
    brief = AdBrief(goal="image", product="꽃다발", price=0, photo_id=None)
    ad = pipeline.generate_ad(brief, _store(), CopyCandidate(headline="봄 꽃다발"), "poster")
    assert ad.size == (1080, 1080)


def _photo(tmp_path):
    p = tmp_path / "제품.jpg"
    Image.new("RGB", (64, 64), (120, 80, 40)).save(p)
    return p


def test_keep_갈래는_원본을_배경으로_쓰고_생성하지_않는다(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "_load_font", lambda size: ImageFont.load_default(size))
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    )
    monkeypatch.setattr(pipeline, "route_photo", lambda data, mime, cut: "keep")

    def _boom(prompt):
        raise AssertionError("keep 갈래는 확산 모델을 부르면 안 된다")

    monkeypatch.setattr(pipeline, "generate_background", _boom)
    brief = AdBrief(goal="image", product="크로플", price=0, photo_id=7)
    ad = pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    assert ad.size == (1080, 1080)


def test_cutout_갈래는_누끼가_결과에_들어간다(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    )
    monkeypatch.setattr(pipeline, "route_photo", lambda data, mime, cut: "cutout")
    monkeypatch.setattr(pipeline, "build_bg_prompt", lambda *a, **k: "bg")
    monkeypatch.setattr(
        pipeline, "generate_background", lambda prompt: Image.new("RGB", (256, 256))
    )

    def _spy(product, headline, sub="", **kwargs):
        seen["product"] = product
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline, "compose_ad", _spy)
    brief = AdBrief(goal="image", product="크로플", price=0, photo_id=7)
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["product"] is not None


def test_generate_갈래는_제품이_든_장면을_그린다(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(compose, "_load_font", lambda size: ImageFont.load_default(size))
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    )
    monkeypatch.setattr(pipeline, "route_photo", lambda data, mime, cut: "generate")

    def _hero(industry, product, tone=""):
        seen["product"] = product
        return "hero prompt"

    monkeypatch.setattr(pipeline, "build_hero_prompt", _hero)

    def _gen(prompt):
        seen["prompt"] = prompt
        return Image.new("RGB", (256, 256))

    monkeypatch.setattr(pipeline, "generate_background", _gen)
    brief = AdBrief(goal="image", product="크로플", price=0, photo_id=7)
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["product"] == "크로플"
    assert seen["prompt"] == "hero prompt"
