"""이미지 백엔드 계약 — 프로필 선택과 폴백 (docs/09).

전부 대역이다. 실제 sd-turbo·OpenAI는 conftest 가드가 원천 차단한다.
"""

from __future__ import annotations

import base64
import io
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import ModuleType

import pytest
from PIL import Image

from app_core import image_backend

LOCAL = Image.new("RGB", (1080, 1080), (1, 2, 3))
GPT = Image.new("RGB", (1080, 1080), (9, 9, 9))
_REAL_OPENAI_EDIT = image_backend._openai_edit
_REAL_OPENAI_RESTAGE = image_backend._openai_restage


@pytest.fixture
def local_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        image_backend.gen_background,
        "generate_background",
        lambda prompt, size=(1080, 1080): LOCAL,
    )


def test_기본_프로필은_로컬이고_OpenAI를_부르지_않는다(
    monkeypatch: pytest.MonkeyPatch,
    local_stub: None,
) -> None:
    """키 없는 기본 환경에서는 OpenAI 경로를 스치지 않아야 한다."""
    monkeypatch.delenv("IMAGE_PROFILE", raising=False)

    assert image_backend.generate_scene("a cafe table") is LOCAL
    assert image_backend.pop_notices() == []


def test_openai_프로필이면_GPT_결과를_쓴다(
    monkeypatch: pytest.MonkeyPatch,
    local_stub: None,
) -> None:
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    monkeypatch.setattr(
        image_backend,
        "_openai_scene",
        lambda prompt, size: GPT,
    )

    assert image_backend.generate_scene("a cafe table") is GPT


def test_GPT가_실패하면_로컬로_폴백하고_안내를_남긴다(
    monkeypatch: pytest.MonkeyPatch,
    local_stub: None,
) -> None:
    """실패해도 광고는 나오지만, 조용히 다른 방식으로 바뀌지는 않는다."""
    monkeypatch.setenv("IMAGE_PROFILE", "openai")

    def _fail(prompt: str, size: tuple[int, int]) -> Image.Image:
        raise RuntimeError("연결 실패")

    monkeypatch.setattr(image_backend, "_openai_scene", _fail)

    assert image_backend.generate_scene("a cafe table") is LOCAL

    notes = image_backend.pop_notices()
    assert len(notes) == 1
    assert "로컬" in notes[0]
    assert "연결 실패" not in notes[0]
    assert image_backend.pop_notices() == []


def test_동시_사용자의_폴백_안내가_서로_섞이지_않는다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 서버를 함께 써도 각 요청은 자기 안내 한 건만 받아야 한다."""
    monkeypatch.setenv("IMAGE_PROFILE", "openai")
    both_fell_back = Barrier(2)

    def _fail(prompt: str, size: tuple[int, int]) -> Image.Image:
        raise RuntimeError(f"{prompt}: 연결 실패")

    def _local(prompt: str, size: tuple[int, int] = (1080, 1080)) -> Image.Image:
        both_fell_back.wait(timeout=5)
        return LOCAL

    monkeypatch.setattr(image_backend, "_openai_scene", _fail)
    monkeypatch.setattr(image_backend.gen_background, "generate_background", _local)

    def _request(label: str) -> list[str]:
        assert image_backend.generate_scene(label) is LOCAL
        return image_backend.pop_notices()

    with ThreadPoolExecutor(max_workers=2) as pool:
        notes_by_user = list(pool.map(_request, ("첫 사용자", "둘째 사용자")))

    expected = ["GPT 이미지 연결이 실패해 로컬 모델로 만들었습니다."]
    assert notes_by_user == [expected, expected]
    assert image_backend.pop_notices() == []


def test_GPT_사진_보정이_성공하면_편집_결과를_쓴다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Image.new("RGB", (64, 32), (1, 2, 3))
    seen: dict[str, object] = {}

    def _edit(photo, product, tone, size):
        seen.update(photo=photo, product=product, tone=tone, size=size)
        return GPT

    monkeypatch.setattr(image_backend, "_openai_edit", _edit)

    assert image_backend.edit_photo(source, "크로플", "차분하게") is GPT
    assert seen == {
        "photo": source,
        "product": "크로플",
        "tone": "차분하게",
        "size": (1080, 1080),
    }
    assert image_backend.pop_notices() == []


def test_OpenAI_편집호출에_PNG와_상품보존_계약을_전달한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실 SDK 표면을 대역으로 호출해 파일·인자·프롬프트 모양을 고정한다."""
    output = io.BytesIO()
    Image.new("RGB", (16, 16), (9, 8, 7)).save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode()
    seen: dict[str, object] = {}

    class _Images:
        def edit(self, **kwargs):
            seen.update(kwargs)
            return type("Response", (), {"data": [type("Datum", (), {"b64_json": encoded})()]})()

    class _Client:
        images = _Images()

    fake_openai = ModuleType("openai")
    fake_openai.__dict__["OpenAI"] = _Client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    monkeypatch.setattr(image_backend, "_openai_edit", _REAL_OPENAI_EDIT)

    result = image_backend._openai_edit(
        Image.new("RGB", (64, 32), (1, 2, 3)), "크로플", "차분", (32, 32)
    )

    assert result.size == (32, 32)
    assert seen["model"] == "gpt-image-2"
    assert seen["size"] == "1024x1024"
    files = seen["image"]
    assert isinstance(files, list)
    assert files[0].name == "input.png"
    prompt = str(seen["prompt"])
    assert "Do not add, remove" in prompt
    assert "ingredient, topping" in prompt
    assert "No overlay text" in prompt


def test_GPT_사진_보정이_실패하면_원본과_안내를_쓴다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Image.new("RGB", (64, 32), (1, 2, 3))

    def _fail(*_args, **_kwargs):
        raise RuntimeError("비밀 외부 오류")

    monkeypatch.setattr(image_backend, "_openai_edit", _fail)

    result = image_backend.edit_photo(source, "크로플")

    assert result.size == (1080, 1080)
    assert result.getpixel((0, 0)) == (1, 2, 3)
    notes = image_backend.pop_notices()
    assert notes == ["사진 보정에 실패해 원본 사진으로 만들었습니다."]
    assert "비밀 외부 오류" not in notes[0]


def test_AI_광고_재촬영이_성공하면_연출_결과로_표시한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Image.new("RGB", (64, 32), (1, 2, 3))
    seen: dict[str, object] = {}

    def _restage(photo, **kwargs):
        seen.update(photo=photo, kwargs=kwargs)
        return GPT

    monkeypatch.setattr(image_backend, "_openai_restage", _restage)

    result = image_backend.restage_photo(
        source,
        product="크로플",
        industry="카페",
        situation="신메뉴",
        tone="따뜻하게",
        style="simple",
    )

    assert result.image is GPT
    assert result.staged is True
    assert seen["photo"] is source
    assert seen["kwargs"]["style"] == "simple"


def test_AI_재촬영은_고품질과_스타일별_연출을_API에_전달한다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), (9, 8, 7)).save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode()
    seen: dict[str, object] = {}

    class _Images:
        def edit(self, **kwargs):
            seen.update(kwargs)
            return type("Response", (), {"data": [type("Datum", (), {"b64_json": encoded})()]})()

    class _Client:
        images = _Images()

    fake_openai = ModuleType("openai")
    fake_openai.__dict__["OpenAI"] = _Client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setattr(image_backend, "_openai_restage", _REAL_OPENAI_RESTAGE)

    result = image_backend._openai_restage(
        Image.new("RGB", (64, 32), (1, 2, 3)),
        product="크로플",
        industry="카페",
        situation="신메뉴",
        tone="따뜻하게",
        extra="",
        transcript="",
        style="simple",
        size=(32, 32),
    )

    assert result.size == (32, 32)
    assert seen["model"] == "gpt-image-2"
    assert seen["quality"] == "high"
    prompt = str(seen["prompt"])
    assert "creative commercial reshoot" in prompt
    assert "upper left" in prompt
    assert "Do not render any visible or legible typography anywhere" in prompt
    assert "signs, menus, price tags, labels" in prompt
    assert "lettering is unreadable" in prompt
    assert "Preserve every visible product exactly" not in prompt

    poster_prompt = image_backend._restage_prompt(
        product="크로플",
        industry="카페",
        situation="신메뉴",
        tone="따뜻하게",
        extra="",
        transcript="",
        style="poster",
    )
    assert "information poster" in poster_prompt
    assert poster_prompt != prompt

    image_backend._openai_restage(
        Image.new("RGB", (64, 32), (1, 2, 3)),
        product="크로플",
        industry="카페",
        situation="신메뉴",
        tone="따뜻하게",
        extra="",
        transcript="",
        style="poster",
        size=(30, 20),
    )
    assert seen["size"] == "1536x1024"


def test_AI_재촬영이_실패하면_안전보정하고_연출표시하지_않는다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Image.new("RGB", (64, 32), (1, 2, 3))
    enhanced = Image.new("RGB", (64, 32), (4, 5, 6))
    monkeypatch.setattr(
        image_backend,
        "_openai_restage",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("비밀 외부 오류")),
    )
    monkeypatch.setattr(image_backend, "enhance_uploaded_photo", lambda photo: enhanced)

    result = image_backend.restage_photo(source, product="크로플")

    assert result.image is enhanced
    assert result.staged is False
    assert image_backend.pop_notices() == [
        "AI 광고 촬영에 실패해 원본 사진을 안전 보정해 사용했습니다."
    ]


def test_AI와_안전보정이_모두_실패하면_RGB_원본을_쓴다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Image.new("RGBA", (8, 4), (1, 2, 3, 99))
    monkeypatch.setattr(
        image_backend,
        "_openai_restage",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("API 실패")),
    )
    monkeypatch.setattr(
        image_backend,
        "enhance_uploaded_photo",
        lambda photo: (_ for _ in ()).throw(OSError("보정 실패")),
    )

    result = image_backend.restage_photo(source, product="크로플")

    assert result.staged is False
    assert result.image.mode == "RGB"
    assert result.image.size == source.size
    assert result.image.getpixel((0, 0)) == (1, 2, 3)


def test_모르는_프로필이면_조용히_넘어가지_않는다(
    monkeypatch: pytest.MonkeyPatch,
    local_stub: None,
) -> None:
    """opneai 같은 오타가 조용히 local로 처리되면 원인을 찾기 어렵다."""
    monkeypatch.setenv("IMAGE_PROFILE", "opneai")

    with pytest.raises(ValueError, match="IMAGE_PROFILE"):
        image_backend.generate_scene("a cafe table")
