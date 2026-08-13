"""LLM 백엔드 선택 — MODEL_PROFILE 로 갈아끼울 수 있는지 확인한다."""

import pytest

from app_core.llm import StubClient, get_client, get_vision_client, profile


def test_기본값은_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_PROFILE", raising=False)
    assert isinstance(get_client(), StubClient)


def test_stub은_빈_응답만_돌려준다() -> None:
    assert StubClient().complete_json("sys", "user") == {}


def test_지금_쓰는_프로필을_알려준다(monkeypatch: pytest.MonkeyPatch) -> None:
    """화면이 "왜 결과가 비었는지" 를 설명하려면 이 값이 필요하다."""
    monkeypatch.delenv("MODEL_PROFILE", raising=False)
    assert profile() == "stub"
    monkeypatch.setenv("MODEL_PROFILE", "openai")
    assert profile() == "openai"


def test_local은_아직_안_붙였다고_알린다(monkeypatch: pytest.MonkeyPatch) -> None:
    """조용히 다른 걸로 대체되면 안 된다."""
    monkeypatch.setenv("MODEL_PROFILE", "local")
    with pytest.raises(NotImplementedError):
        get_client()


def test_모르는_프로필은_거부한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROFILE", "gemini")
    with pytest.raises(ValueError, match="모르는"):
        get_client()


# ── 사진 읽기 ────────────────────────────────────────────────


def test_사진도_기본값은_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_PROFILE", raising=False)
    assert isinstance(get_vision_client(), StubClient)


def test_stub은_사진을_봐도_빈_응답() -> None:
    assert StubClient().read_image("sys", b"img", "image/png") == {}


def test_사진은_모르는_프로필이어도_안_터진다(monkeypatch: pytest.MonkeyPatch) -> None:
    """사진 설명은 없어도 문구가 만들어진다. 여기서 터뜨리면 전체가 멈춘다."""
    monkeypatch.setenv("MODEL_PROFILE", "local")
    assert isinstance(get_vision_client(), StubClient)
