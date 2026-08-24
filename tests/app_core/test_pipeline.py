"""조립 부품 테스트 — 무거운 부품(확산 모델·LLM·누끼)은 대역으로 바꾼다."""

from PIL import Image, ImageFont

from app_core import fonts, image_backend, photo_router, pipeline
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

    프롬프트가 셋인 이유: 사진 없는 감성형은 촬영 장면(scene),
    포스터는 작은 주인공(hero),
    누끼가 있으면 빈 배경(gb)을 쓴다.

    글꼴은 fonts.load 하나만 잡으면 된다 —
    compose 가 갖고 있던 별도 목록은 #18 에서 fonts.py 로 합쳐졌다.
    """
    monkeypatch.setattr(fonts, "load", _fake_font)
    monkeypatch.setattr(pipeline, "build_bg_prompt", lambda *a, **k: "base prompt")
    monkeypatch.setattr(pipeline, "build_hero_prompt", lambda *a, **k: "hero prompt")
    monkeypatch.setattr(pipeline, "build_scene_prompt", lambda *a, **k: "scene prompt")


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
    # 사진이 없으면 scene 프롬프트가 바탕이 된다 — 레퍼런스는 그 뒤에 붙는다
    assert seen["prompt"] == "scene prompt, dim candlelight, dark wood"


def test_레퍼런스가_없으면_프롬프트를_안_건드린다(tmp_path, monkeypatch):
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    seen = {}

    def fake_bg(prompt):
        seen["prompt"] = prompt
        return Image.new("RGB", (1080, 1080))

    _both_backends(monkeypatch, fake_bg)

    pipeline.generate_ad(_brief(), _store(), CopyCandidate(headline="크로플"), "simple")
    assert seen["prompt"] == "scene prompt"  # 레퍼런스가 안 붙었다


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
    # 긴 촬영 기획(scene)이 아니라 짧은 주인공 프롬프트여야 한다 — 스케치 모델의
    # CLIP 입력이 짧아 긴 프롬프트는 잘리고 구도 지시가 약해진다.
    # (배경 프롬프트("빈 탁자")도 안 된다 — 제품이 없어 흐릿한 덩어리가 나온다)
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


def test_사진을_올린_감성형은_OpenAI에서_광고_재촬영한다(tmp_path, monkeypatch):
    """감성형은 전용 연출로 한 번 재촬영하고 이후 Pillow가 문구를 얹는다."""
    source = _photo(tmp_path)
    restaged = Image.new("RGB", (1080, 1080), (121, 81, 41))
    seen: dict[str, object] = {}
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: source)

    def _restage(photo, **kwargs):
        seen.update(photo=photo, kwargs=kwargs)
        return image_backend.RestageResult(restaged, staged=True)

    def _forbidden(*args, **kwargs):
        raise AssertionError("업로드 사진 재촬영에서 누끼·별도 장면 생성을 호출하면 안 된다")

    monkeypatch.setattr(pipeline, "restage_photo", _restage)
    monkeypatch.setattr(pipeline, "remove_background", _forbidden)
    monkeypatch.setattr(pipeline, "generate_scene", _forbidden)
    monkeypatch.setattr(pipeline, "generate_background", _forbidden)
    monkeypatch.setattr(photo_router, "route_photo", _forbidden)

    materials = pipeline.prepare_materials(
        AdBrief(
            goal="image",
            product="크로플",
            price=0,
            photo_id=7,
            situation="신메뉴",
            tone="따뜻하게",
        ),
        _store(),
        "simple",
    )

    assert isinstance(materials, pipeline.SimpleMaterials)
    assert seen["photo"] is not None
    assert seen["kwargs"]["style"] == "simple"
    assert seen["kwargs"]["product"] == "크로플"
    assert seen["kwargs"]["situation"] == "신메뉴"
    assert materials.product is None
    assert materials.background is restaged
    assert materials.preserved_photo is True
    assert materials.staged is True


def test_실사진_AI재촬영이_실패하면_안전보정_결과를_쓴다(tmp_path, monkeypatch):
    source = _photo(tmp_path)
    enhanced = Image.new("RGB", (64, 64), (122, 82, 42))
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: source)
    monkeypatch.setattr(
        pipeline,
        "restage_photo",
        lambda *args, **kwargs: image_backend.RestageResult(enhanced, staged=False),
    )

    materials = pipeline.prepare_materials(
        AdBrief(goal="image", product="크로플", price=0, photo_id=7), _store(), "simple"
    )

    assert isinstance(materials, pipeline.SimpleMaterials)
    assert materials.background is enhanced
    assert materials.staged is False


def test_openai여도_사진과_스케치가_같이_있으면_기존_합성을_유지한다(tmp_path, monkeypatch):
    """OpenAI 프로필도 스케치의 구도·실상품 누끼 계약을 바꾸지 않는다."""
    _cutout_ready(tmp_path, monkeypatch)
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    seen = _watch(monkeypatch)

    brief = _brief().model_copy(update={"photo_id": 1, "sketch_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert seen["스케치로"] is True
    assert seen["prompt"] == "base prompt"
    assert seen["누끼"] is True


def test_사진과_레퍼런스는_청소된_누끼를_배경에_얹는다(tmp_path, monkeypatch):
    """명시한 레퍼런스가 있으면 상품 누끼를 보존하고 분위기만 생성한다."""
    raw = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    cleaned = Image.new("RGBA", (10, 10), (1, 2, 3, 255))
    _simple_ready(monkeypatch)
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: _photo(tmp_path))
    monkeypatch.setattr(pipeline, "remove_background", lambda im: raw)
    monkeypatch.setattr(pipeline, "remove_crumbs", lambda cut: cleaned)
    monkeypatch.setattr(pipeline.ref_style, "describe_style", lambda *a, **k: "warm light")
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080)))

    materials = pipeline.prepare_materials(
        AdBrief(goal="image", product="크로플", price=0, photo_id=7, ref_id=8),
        _store(),
        "simple",
    )

    assert isinstance(materials, pipeline.SimpleMaterials)
    assert materials.product is cleaned


def test_사진_있는_포스터는_누끼_없이_사진_전체를_카드로_쓴다(tmp_path, monkeypatch):
    """포스터 전용 재촬영본을 사진 카드로 넘기고 연출 표기도 전달한다."""
    source = _photo(tmp_path)
    restaged = Image.new("RGB", (1080, 1080), (12, 34, 56))
    seen = {}
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: source)

    def _restage(photo, **kwargs):
        seen["restage_kwargs"] = kwargs
        return image_backend.RestageResult(restaged, staged=True)

    monkeypatch.setattr(pipeline, "restage_photo", _restage)

    def _forbidden(*args, **kwargs):
        raise AssertionError("사진 있는 포스터에서 누끼·별도 포스터 기획을 부르면 안 된다")

    monkeypatch.setattr(pipeline, "remove_background", _forbidden)
    monkeypatch.setattr(pipeline, "plan_poster", _forbidden)
    monkeypatch.setattr(pipeline, "generate_poster", _forbidden)

    def _spy(photo, shop, **kwargs):
        seen.update(photo=photo, shop=shop, kwargs=kwargs)
        return Image.new("RGB", (1080, 1080))

    monkeypatch.setattr(pipeline, "generate_uploaded_photo_poster", _spy)
    brief = AdBrief(goal="image", product="골드 커플링", price=0, photo_id=7)
    pipeline.generate_ad(
        brief,
        _store(),
        CopyCandidate(headline="영원한 사랑의 상징", sub="두 사람의 특별한 순간"),
        "poster",
    )

    assert seen["restage_kwargs"]["style"] == "poster"
    assert seen["photo"] is restaged
    assert seen["shop"] == _store().name
    assert seen["kwargs"]["product_name"] == "골드 커플링"
    assert seen["kwargs"]["sub"] == "두 사람의 특별한 순간"
    assert seen["kwargs"]["staged"] is True


# ── 제품 사진 + 스케치 조합 ──────────────────────────────────
#
# PHOTO_SLOTS 셋은 서로 독립이라 사장님이 동시에 올릴 수 있다. 조합마다
# **제품이 정확히 한 번만** 나와야 한다 — 배경에 그리든 누끼를 얹든 하나로.


def _cutout_ready(tmp_path, monkeypatch):
    """레퍼런스·스케치·포스터가 있는 사진 경로의 누끼 부품을 대역으로 세운다."""
    _simple_ready(monkeypatch)
    photo = tmp_path / "제품.png"
    Image.new("RGB", (64, 64), (120, 80, 40)).save(photo)
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: photo)
    monkeypatch.setattr(
        pipeline, "remove_background", lambda im: Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    )
    monkeypatch.setattr(pipeline, "remove_crumbs", lambda cut: cut)


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


def test_레퍼런스를_같이_주면_실상품_누끼와_분위기를_함께_쓴다(tmp_path, monkeypatch):
    """레퍼런스는 생성 배경에만 반영하고 실제 상품 누끼는 그대로 보존한다."""
    _cutout_ready(tmp_path, monkeypatch)
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    monkeypatch.setattr(pipeline.photo_store, "load", lambda pid: (b"x", "image/png"))
    monkeypatch.setattr(pipeline.ref_style, "describe_style", lambda *a, **k: "warm light")

    seen = {}

    def _bg(prompt):
        seen["prompt"] = prompt
        return Image.new("RGB", (1080, 1080))

    _both_backends(monkeypatch, _bg)
    materials = pipeline.prepare_materials(
        _brief().model_copy(update={"photo_id": 7, "ref_id": 8}), _store(), "simple"
    )
    assert materials.product is not None  # 기존 누끼+배경 경로
    assert "warm light" in seen["prompt"]  # 레퍼런스 분위기가 실제로 반영됐다


def test_스케치만_있으면_스케치가_제품을_그린다(tmp_path, monkeypatch):
    """얹을 누끼가 없으니 스케치가 상품을 그려야 한다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    seen = _watch(monkeypatch)

    brief = _brief().model_copy(update={"sketch_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert seen["prompt"] == "hero prompt"
    assert seen["누끼"] is False


def test_로컬에서_사진만_있으면_비용없이_안전_보정한다(tmp_path, monkeypatch):
    source = _photo(tmp_path)
    enhanced = Image.new("RGB", (64, 64), (121, 81, 41))
    monkeypatch.setenv("IMAGE_PROFILE", "local")
    monkeypatch.setattr(pipeline.photo_store, "path_of", lambda pid: source)
    monkeypatch.setattr(pipeline, "enhance_uploaded_photo", lambda photo: enhanced)

    materials = pipeline.prepare_materials(
        _brief().model_copy(update={"photo_id": 1}), _store(), "simple"
    )

    assert isinstance(materials, pipeline.SimpleMaterials)
    assert materials.background is enhanced
    assert materials.product is None


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
    """안전 보정본은 **사장님이 찍은 진짜 사진**이므로 연출 표기를 붙이지 않는다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    calls = _notice_spy(monkeypatch)

    brief = _brief().model_copy(update={"photo_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert not calls, "진짜 사진에 '연출된 이미지' 를 붙이면 그것이 거짓말이다"


def test_사장님_사진을_AI로_재촬영하면_연출_표기가_붙는다(tmp_path, monkeypatch):
    """원본을 참고했어도 AI가 새 광고 사진을 그렸다면 사실대로 표시한다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    calls = _notice_spy(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "restage_photo",
        lambda *args, **kwargs: image_backend.RestageResult(
            Image.new("RGB", (1080, 1080), (10, 20, 30)), staged=True
        ),
    )

    brief = _brief().model_copy(update={"photo_id": _put()})
    pipeline.generate_ad(brief, _store(), CopyCandidate(headline="크로플"), "simple")

    assert calls, "AI 재촬영 사진인데 연출 표기가 붙지 않았다"


def test_누끼를_얹으면_표기하지_않는다(tmp_path, monkeypatch):
    """배경은 AI 가 그렸어도 **상품은 사장님 것**이다. 표기 대상은 상품 쪽이다."""
    _photo_dir(tmp_path, monkeypatch)
    _simple_ready(monkeypatch)
    calls = _notice_spy(monkeypatch)
    cut = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    monkeypatch.setattr(pipeline, "remove_background", lambda im: cut)
    monkeypatch.setattr(pipeline, "remove_crumbs", lambda c: cut)
    monkeypatch.setattr(pipeline.ref_style, "describe_style", lambda *a, **k: "warm light")
    _both_backends(monkeypatch, lambda prompt: Image.new("RGB", (1080, 1080), (10, 20, 30)))

    brief = _brief().model_copy(update={"photo_id": _put(), "ref_id": _put()})
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

    def _compose(
        product,
        headline,
        sub="",
        size=(1080, 1080),
        background=None,
        staged=False,
        shop="",
        preserved_photo=False,
    ):
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
