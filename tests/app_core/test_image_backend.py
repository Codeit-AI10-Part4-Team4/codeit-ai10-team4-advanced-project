"""이미지 백엔드 계약 — 프로필 선택과 폴백 (docs/09).

전부 대역이다. 실제 sd-turbo·OpenAI는 conftest 가드가 원천 차단한다.
"""

from __future__ import annotations

import pytest
from PIL import Image

from app_core import image_backend

LOCAL = Image.new("RGB", (1080, 1080), (1, 2, 3))
GPT = Image.new("RGB", (1080, 1080), (9, 9, 9))


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


def test_모르는_프로필이면_조용히_넘어가지_않는다(
    monkeypatch: pytest.MonkeyPatch,
    local_stub: None,
) -> None:
    """opneai 같은 오타가 조용히 local로 처리되면 원인을 찾기 어렵다."""
    monkeypatch.setenv("IMAGE_PROFILE", "opneai")

    with pytest.raises(ValueError, match="IMAGE_PROFILE"):
        image_backend.generate_scene("a cafe table")
