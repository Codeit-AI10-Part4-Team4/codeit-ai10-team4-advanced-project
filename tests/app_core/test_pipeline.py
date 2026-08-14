"""조립 부품 테스트 — 무거운 부품(확산 모델·LLM·누끼)은 대역으로 바꾼다."""

from PIL import Image, ImageFont

from app_core import compose, fonts, pipeline
from app_core.poster_plan import PosterPlan
from app_core.schema import AdBrief, CopyCandidate, Store


def _fake_font(role: str, size: int) -> ImageFont.FreeTypeFont:
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
    monkeypatch.setattr(pipeline, "build_bg_prompt", lambda *a, **k: "prompt")
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


# ── 레퍼런스(2번) · 스케치(4번) 연결 ──────────────────────────
#
# 둘 다 photo_store 에 올라온 번호를 주문서가 들고 온다. 여기서 확인하는 것은
# **번호가 있을 때 다른 길로 가는가** 이지 그림 자체가 아니다.


def _photo_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ADS_PHOTO_DIR", str(tmp_path / "photos"))


def _put(color=(255, 255, 255)) -> int:
    """보관함에 사진 한 장 넣고 번호를 돌려준다."""
    import io

    from app_core import photo_store

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return photo_store.save(buf.getvalue(), "x.png")


def _simple_ready(monkeypatch):
    """simple 형태를 돌리는 데 필요한 무거운 부품을 전부 대역으로.

    프롬프트가 둘인 이유: 스케치가 있으면 **주인공** 프롬프트를 쓴다. 배경
    프롬프트는 "빈 탁자, 흐린 뒤쪽"을 지시해서 스케치와 부딪힌다.
    """
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(compose, "_load_font", lambda size: ImageFont.load_default(size))
    monkeypatch.setattr(pipeline, "build_bg_prompt", lambda *a, **k: "base prompt")
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero prompt")


def test_레퍼런스가_있으면_프롬프트에_분위기가_붙는다(tmp_path, monkeypatch):
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    monkeypatch.setattr(
        pipeline.ref_style, "describe_style", lambda *a, **k: "dim candlelight, dark wood"
    )
    seen = {}

    def fake_bg(prompt):
        seen["prompt"] = prompt
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline, "generate_background", fake_bg)

    brief = _brief().model_copy(update={"ref_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["prompt"] == "base prompt, dim candlelight, dark wood"


def test_레퍼런스가_없으면_프롬프트를_안_건드린다(tmp_path, monkeypatch):
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    seen = {}

    def fake_bg(prompt):
        seen["prompt"] = prompt
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline, "generate_background", fake_bg)

    pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["prompt"] == "base prompt"


def test_보관함에_레퍼런스가_없어도_광고는_만든다(tmp_path, monkeypatch):
    """번호는 남았는데 파일이 사라진 경우. 분위기만 못 얹고 계속 간다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    monkeypatch.setattr(
        pipeline, "generate_background", lambda prompt: Image.new("RGB", (1080, 1080))
    )
    brief = _brief().model_copy(update={"ref_id": 999})
    assert pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")


def test_스케치가_있으면_그쪽으로_그린다(tmp_path, monkeypatch):
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    monkeypatch.setattr(
        pipeline, "generate_background", lambda prompt: Image.new("RGB", (1080, 1080), (1, 1, 1))
    )
    called = {}

    def fake_sketch(sketch, prompt, **kw):
        called["prompt"] = prompt
        called["size"] = sketch.size
        return Image.new("RGB", (1080, 1080), (2, 2, 2))

    monkeypatch.setattr(pipeline.sketch_gen, "generate_from_sketch", fake_sketch)

    brief = _brief().model_copy(update={"sketch_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    # 배경("빈 탁자")이 아니라 주인공 프롬프트여야 한다 — 안 그러면 그린 것이
    # 흐릿한 덩어리로 나온다. 실제로 그랬다.
    assert called["prompt"] == "hero prompt"
    assert called["size"] == (64, 64)


def test_스케치가_없으면_평소대로_그린다(tmp_path, monkeypatch):
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    monkeypatch.setattr(
        pipeline, "generate_background", lambda prompt: Image.new("RGB", (1080, 1080))
    )

    def boom(*a, **k):
        raise AssertionError("스케치가 없는데 sketch_gen 을 불렀다")

    monkeypatch.setattr(pipeline.sketch_gen, "generate_from_sketch", boom)
    assert pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")


def test_레퍼런스와_스케치를_같이_쓸_수_있다(tmp_path, monkeypatch):
    """구도는 스케치가, 분위기는 레퍼런스가 맡는다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    monkeypatch.setattr(pipeline.ref_style, "describe_style", lambda *a, **k: "warm light")
    called = {}

    def fake_sketch(sketch, prompt, **kw):
        called["prompt"] = prompt
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline.sketch_gen, "generate_from_sketch", fake_sketch)

    brief = _brief().model_copy(update={"ref_id": _put(), "sketch_id": _put((0, 0, 0))})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    assert called["prompt"] == "hero prompt, warm light"
