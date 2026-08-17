"""조립 부품 테스트 — 무거운 부품(확산 모델·LLM·누끼)은 대역으로 바꾼다."""

from PIL import Image, ImageFont

from app_core import fonts, photo_router, pipeline
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
    seen = {}
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    )
    monkeypatch.setattr(pipeline, "route_photo", lambda data, mime, cut: "keep")

    def _boom(prompt):
        raise AssertionError("keep 갈래는 확산 모델을 부르면 안 된다")

    monkeypatch.setattr(pipeline, "generate_background", _boom)

    def _spy(product, headline, sub="", background=None, **kwargs):
        seen["product"] = product
        seen["background"] = background
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline, "compose_ad", _spy)
    brief = AdBrief(goal="image", product="크로플", price=0, photo_id=7)
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["product"] is None
    assert seen["background"] is not None
    assert seen["background"].size == (64, 64)  # 원본 사진 크기 그대로


def test_cutout_갈래는_청소된_누끼가_그대로_전달된다(tmp_path, monkeypatch):
    seen = {}
    cleaned = Image.new("RGBA", (10, 10))  # keep_largest 가 돌려준 표식
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    )
    monkeypatch.setattr(pipeline, "remove_crumbs", lambda cut: cleaned)
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
    assert seen["product"] is cleaned


def test_generate_갈래는_제품이_든_장면을_그린다(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(fonts, "load", _fake_font)
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


def test_라우터는_청소_전_누끼를_받는다(tmp_path, monkeypatch):
    """청소를 먼저 하면 라우터가 보기 전에 상품이 사라진다 — 순서를 고정한다."""
    seen = {}
    raw = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(pipeline, "remove_background", lambda im: raw)
    monkeypatch.setattr(pipeline, "remove_crumbs", lambda cut: Image.new("RGBA", (64, 64)))

    def _route(data, mime, cut):
        seen["cut"] = cut
        return "keep"

    monkeypatch.setattr(pipeline, "route_photo", _route)
    brief = AdBrief(goal="image", product="크로플", price=0, photo_id=7)
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["cut"] is raw  # 청소 전 누끼여야 한다


def test_poster는_다제품을_하나로_줄이지_않는다(tmp_path, monkeypatch):
    """포스터 제품 이미지까지 두 조각이 살아서 간다 — 가장 큰 것만 남기기 금지."""
    seen = {}
    two = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    two.paste((255, 255, 255, 255), (8, 8, 40, 40))  # 큰 상품 25%
    two.paste((255, 255, 255, 255), (48, 48, 56, 56))  # 작은 상품 1.6%
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(pipeline, "remove_background", lambda im: two)
    monkeypatch.setattr(
        pipeline,
        "plan_poster",
        lambda **kwargs: PosterPlan(
            tagline="t", badge="b", date_line="", features=["a|b"], event="", palette="fresh_mint"
        ),
    )

    def _spy(product, shop, **kwargs):
        seen["pieces"] = photo_router.significant_pieces(product)
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline, "generate_poster", _spy)
    brief = AdBrief(goal="image", product="크로플", price=0, photo_id=7)
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "poster")
    assert seen["pieces"] == 2  # 두 상품이 그대로 포스터로 간다
