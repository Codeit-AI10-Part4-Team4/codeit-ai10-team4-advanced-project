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


def _both_backends(monkeypatch, fake):
    """로컬 배경 생성과 새 이미지 백엔드를 같은 대역으로 바꾼다.

    포스터형은 generate_background를 사용하고,
    감성형은 generate_scene을 사용하므로 둘 다 막아야 실제 모델이 호출되지 않는다.
    """
    monkeypatch.setattr(pipeline, "generate_background", fake)
    monkeypatch.setattr(pipeline, "generate_scene", fake)


def test_poster_style_uses_plan(monkeypatch):
    """포스터 형태는 기획 부품이 채운 내용으로 그린다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero prompt")
    _both_backends(
        monkeypatch,
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
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080), (10, 20, 30)))
    ad = pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")
    assert ad.size == (1080, 1080)


def test_poster_style_without_photo_generates_hero(monkeypatch):
    """사진이 없으면 주인공 이미지를 생성해 채운다 — 오른쪽이 비면 안 된다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero prompt")
    _both_backends(
        monkeypatch,
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

    프롬프트가 둘인 이유: **얹을 누끼가 없으면** 주인공 프롬프트를 쓴다.
    배경 프롬프트("빈 탁자")는 누끼를 얹을 캔버스라 그 위에 올릴 게 없으면
    광고 대상이 사라진다.

    글꼴은 fonts.load 하나만 잡으면 된다 — compose 가 갖고 있던 별도 목록은
    #18 에서 fonts.py 로 합쳐졌다.
    """
    monkeypatch.setattr(fonts, "load", _fake_font)
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

    _both_backends(monkeypatch, fake_bg)

    brief = _brief().model_copy(update={"ref_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")
    # 사진이 없으면 hero 프롬프트가 바탕이 된다(#22) — 레퍼런스는 그 뒤에 붙는다
    assert seen["prompt"] == "hero prompt, dim candlelight, dark wood"


def test_레퍼런스가_없으면_프롬프트를_안_건드린다(tmp_path, monkeypatch):
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    seen = {}

    def fake_bg(prompt):
        seen["prompt"] = prompt
        return Image.new("RGB", (1080, 1080))

    _both_backends(monkeypatch, fake_bg)

    pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["prompt"] == "hero prompt"  # 레퍼런스가 안 붙었다


def test_보관함에_레퍼런스가_없어도_광고는_만든다(tmp_path, monkeypatch):
    """번호는 남았는데 파일이 사라진 경우. 분위기만 못 얹고 계속 간다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080)))
    brief = _brief().model_copy(update={"ref_id": 999})
    assert pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")


def test_스케치가_있으면_그쪽으로_그린다(tmp_path, monkeypatch):
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080), (1, 1, 1)))
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
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080)))

    def boom(*a, **k):
        raise AssertionError("스케치가 없는데 sketch_gen 을 불렀다")

    monkeypatch.setattr(pipeline.sketch_gen, "generate_from_sketch", boom)
    assert pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")


def test_감성형_배경은_이미지_백엔드가_그린다(monkeypatch):
    """감성형 배경이 새 이미지 백엔드를 거치는지 확인한다."""
    _simple_ready(monkeypatch)

    def _wrong_door(prompt):
        raise AssertionError("감성형이 백엔드를 거치지 않고 로컬 모델을 직접 불렀다")

    monkeypatch.setattr(pipeline, "generate_background", _wrong_door)
    monkeypatch.setattr(
        pipeline,
        "generate_scene",
        lambda prompt: Image.new("RGB", (1080, 1080)),
    )

    materials = pipeline.prepare_materials(_brief(), _store(), "simple")

    assert isinstance(materials, pipeline.SimpleMaterials)
    assert materials.background.size == (1080, 1080)


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

    _both_backends(monkeypatch, _boom)

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
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (256, 256)))

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

    _both_backends(monkeypatch, _gen)
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


# ── 제품 사진 + 스케치 조합 ──────────────────────────────────
#
# PHOTO_SLOTS 셋은 서로 독립이라 사장님이 동시에 올릴 수 있다. 조합마다
# **제품이 정확히 한 번만** 나와야 한다 — 배경에 그리든 누끼를 얹든 하나로.


def _cutout_ready(tmp_path, monkeypatch):
    """사진이 있는 경로. 누끼·갈래 판정을 대역으로 세운다."""
    _simple_ready(monkeypatch)
    photo = tmp_path / "제품.png"
    Image.new("RGB", (64, 64), (120, 80, 40)).save(photo)
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: photo)
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    )
    monkeypatch.setattr(pipeline, "remove_crumbs", lambda cut: cut)
    monkeypatch.setattr(pipeline, "route_photo", lambda d, m, c: "cutout")


def _watch(monkeypatch):
    """어느 프롬프트로 그렸는지 · 누끼를 얹었는지 붙잡는다."""
    seen: dict = {}

    def bg(prompt):
        seen["prompt"] = prompt
        return Image.new("RGB", (512, 512))

    def sketch(image, prompt, **kw):
        seen["prompt"] = prompt
        seen["스케치로"] = True
        return Image.new("RGB", (512, 512))

    def compose(product, headline, sub="", background=None, **kw):
        seen["누끼"] = product is not None
        return Image.new("RGB", (1080, 1080))

    _both_backends(monkeypatch, bg)
    monkeypatch.setattr(pipeline.sketch_gen, "generate_from_sketch", sketch)
    monkeypatch.setattr(pipeline, "compose_ad", compose)
    return seen


def test_사진과_스케치를_같이_올려도_제품이_하나다(tmp_path, monkeypatch):
    """전에 여기서 제품이 둘로 나왔다.

    스케치가 있다고 hero 프롬프트로 가면 **배경에 제품이 그려지는데**
    그 위에 누끼까지 얹혀서 한 장에 제품이 둘이 된다.
    """
    _cutout_ready(tmp_path, monkeypatch)
    seen = _watch(monkeypatch)

    brief = _brief().model_copy(update={"photo_id": 1, "sketch_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert seen["스케치로"] is True  # 구도는 스케치를 따른다
    assert seen["prompt"] == "base prompt"  # 배경은 빈 무대 — 제품을 안 그린다
    assert seen["누끼"] is True  # 제품은 누끼 한 번만


def test_스케치만_있으면_스케치가_제품을_그린다(tmp_path, monkeypatch):
    """얹을 누끼가 없으니 스케치가 상품을 그려야 한다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    seen = _watch(monkeypatch)

    brief = _brief().model_copy(update={"sketch_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert seen["prompt"] == "hero prompt"
    assert seen["누끼"] is False


def test_사진만_있으면_빈_무대에_누끼를_얹는다(tmp_path, monkeypatch):
    _cutout_ready(tmp_path, monkeypatch)
    seen = _watch(monkeypatch)

    brief = _brief().model_copy(update={"photo_id": 1})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert "스케치로" not in seen
    assert seen["prompt"] == "base prompt"
    assert seen["누끼"] is True


def test_사진과_레퍼런스와_스케치를_다_올려도_제품이_하나다(tmp_path, monkeypatch):
    """칸 셋을 다 채우는 것도 화면에서 막지 않는다."""
    _cutout_ready(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline.ref_style, "describe_style", lambda *a, **k: "warm light")
    seen = _watch(monkeypatch)

    brief = _brief().model_copy(update={"photo_id": 1, "ref_id": _put(), "sketch_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert seen["prompt"] == "base prompt, warm light"
    assert seen["누끼"] is True


# ── 연출 표기 ────────────────────────────────────────────────
#
# "제품 사진 없이 만든 광고는 상품을 AI 가 그린 것이라 표기해야 한다"
# (README §생성 모드 · docs/01 §생성 모드).
#
# 여기서 보는 것은 **판단**이다 — 어느 갈래에 표기가 붙는가.
# 실제로 그려지는지는 tests/app_core/test_compose.py 에서 픽셀로 본다.
# 둘을 나눈 이유: 대역만 보면 "부르기는 하는데 아무것도 안 그리는" 상태를 놓친다.


def _notice_spy(monkeypatch) -> list[str]:
    """draw_staged_notice 가 불렸는지 기록한다. compose·poster 양쪽을 한 번에 잡는다 —
    둘 다 compose 모듈의 전역을 호출 시점에 찾기 때문이다."""
    from app_core import compose

    calls: list[str] = []
    monkeypatch.setattr(
        compose, "draw_staged_notice", lambda canvas, corner="bottom": calls.append(corner)
    )
    return calls


def test_사진_없이_만들면_연출_표기가_붙는다(monkeypatch):
    """상품까지 AI 가 그렸다. 표기가 없으면 사장님이 자기 상품 사진인 양 올리게 된다."""
    _simple_ready(monkeypatch)
    calls = _notice_spy(monkeypatch)
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080), (10, 20, 30)))

    pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")

    assert calls, "사진 없이 만든 광고인데 연출 표기가 붙지 않았다"


def test_사진_없이_만든_포스터에도_연출_표기가_붙는다(monkeypatch):
    """포스터는 주인공을 생성해서 채운다 — 그것도 AI 가 그린 상품이다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero prompt")
    calls = _notice_spy(monkeypatch)
    _both_backends(
        monkeypatch,
        lambda prompt: Image.new("RGB", (512, 512), (200, 180, 160)),
    )
    monkeypatch.setattr(
        pipeline,
        "plan_poster",
        lambda **kwargs: PosterPlan(
            tagline="동네 크로플",
            badge="",
            date_line="",
            features=[],
            event="",
            palette="warm_bakery",
        ),
    )

    pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "poster")

    assert calls, "생성한 주인공을 쓰는데 연출 표기가 붙지 않았다"


def test_사장님_사진을_그대로_쓰면_표기하지_않는다(tmp_path, monkeypatch):
    """🪤 keep 갈래는 compose_ad(product=None) 으로 부르지만 화면에 나오는 것은
    **사장님이 찍은 진짜 사진**이다. product 유무로 짐작하면 여기에 딱지가 붙는다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    calls = _notice_spy(monkeypatch)
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    )
    monkeypatch.setattr(pipeline, "route_photo", lambda data, mime, cut: "keep")

    brief = _brief().model_copy(update={"photo_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert not calls, "진짜 사진에 '연출된 이미지' 를 붙이면 그것이 거짓말이다"


def test_누끼를_얹으면_표기하지_않는다(tmp_path, monkeypatch):
    """배경은 AI 가 그렸어도 **상품은 사장님 것**이다. 표기 대상은 상품 쪽이다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    calls = _notice_spy(monkeypatch)
    cut = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    monkeypatch.setattr(pipeline, "remove_background", lambda im: cut)
    monkeypatch.setattr(pipeline, "remove_crumbs", lambda c: cut)
    monkeypatch.setattr(pipeline, "route_photo", lambda data, mime, c: "cutout")
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080), (10, 20, 30)))

    brief = _brief().model_copy(update={"photo_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert not calls


# ── 재료/조판 분리 (PR-A) ──────────────────────────────────────
#
# 계약: 문구는 조판(render_ad)에서만 쓰인다. 문구를 바꿀 때 비싼 단계
# (배경 생성·포스터 기획)가 다시 돌면 분리는 실패다 (광고완성흐름 §4-1).


def test_문구를_바꿔도_재료_생성은_다시_돌지_않는다(monkeypatch):
    """재료 한 번 · 조판 여러 번 — 문구 수정이 비싼 단계를 다시 부르면 안 된다."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "prompt")
    calls = {"bg": 0}

    def _bg(prompt):
        calls["bg"] += 1
        return Image.new("RGB", (1080, 1080), (10, 20, 30))

    _both_backends(monkeypatch, _bg)
    materials = pipeline.prepare_materials(_brief(), _store(), "simple")
    pipeline.render_ad(materials, CopyCandidate(headline="첫 문구"))
    pipeline.render_ad(materials, CopyCandidate(headline="다른 문구"))
    assert calls["bg"] == 1


def test_바뀐_문구가_조판에_그대로_전달된다(monkeypatch):
    """픽셀 비교가 아니라 인자로 확인한다 — compose 가 받은 headline 이 증거다."""
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "prompt")
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080)))
    seen: list[str] = []

    def _compose(product, headline, sub="", size=(1080, 1080), background=None, staged=False):
        seen.append(headline)
        return Image.new("RGB", size)

    monkeypatch.setattr(pipeline, "compose_ad", _compose)
    materials = pipeline.prepare_materials(_brief(), _store(), "simple")
    pipeline.render_ad(materials, CopyCandidate(headline="첫 문구"))
    pipeline.render_ad(materials, CopyCandidate(headline="다른 문구"))
    assert seen == ["첫 문구", "다른 문구"]


def test_문구만_바꾸면_포스터_기획은_재사용된다(monkeypatch):
    """기획(LLM)은 문구를 모른다 — 문구 수정에 기획이 또 돌면 돈이 또 나간다."""
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero")
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (512, 512)))
    calls = {"plan": 0}

    def _plan(**kwargs):
        calls["plan"] += 1
        return PosterPlan(
            tagline="t", badge="", date_line="", features=[], event="", palette="fresh_mint"
        )

    monkeypatch.setattr(pipeline, "plan_poster", _plan)
    heads: list[str] = []

    def _poster(product, shop, **kwargs):
        heads.append(kwargs["headline"])
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline, "generate_poster", _poster)
    materials = pipeline.prepare_materials(_brief(), _store(), "poster")
    pipeline.render_ad(materials, CopyCandidate(headline="첫 문구"))
    pipeline.render_ad(materials, CopyCandidate(headline="다른 문구"))
    assert calls["plan"] == 1
    assert heads == ["첫 문구", "다른 문구"]


def test_바뀐_주문서로_재료를_다시_만들면_기획에_전달된다(monkeypatch):
    """변경 감지·재호출 결정은 화면(PR-B) 몫이지만, 다시 불렀을 때 새 값이 기획에 가는 건 여기 계약이다."""
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero")
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (512, 512)))
    seen: list[str] = []

    def _plan(**kwargs):
        seen.append(kwargs["tone"])
        return PosterPlan(
            tagline="t", badge="", date_line="", features=[], event="", palette="fresh_mint"
        )

    monkeypatch.setattr(pipeline, "plan_poster", _plan)
    monkeypatch.setattr(pipeline, "generate_poster", lambda *a, **k: Image.new("RGB", (1080, 1080)))
    pipeline.prepare_materials(
        AdBrief(goal="image", product="크로플", price=0, tone="발랄"), _store(), "poster"
    )
    pipeline.prepare_materials(
        AdBrief(goal="image", product="크로플", price=0, tone="차분"), _store(), "poster"
    )
    assert seen == ["발랄", "차분"]
