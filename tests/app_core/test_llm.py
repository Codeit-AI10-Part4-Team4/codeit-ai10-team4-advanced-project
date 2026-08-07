"""LLM 백엔드 선택 — MODEL_PROFILE 로 갈아끼울 수 있는지 확인한다."""

import pytest

from app_core.llm import StubClient, get_client


def test_기본값은_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_PROFILE", raising=False)
    assert isinstance(get_client(), StubClient)


def test_stub은_빈_응답만_돌려준다() -> None:
    assert StubClient().complete_json("sys", "user") == {}


def test_local은_아직_안_붙였다고_알린다(monkeypatch: pytest.MonkeyPatch) -> None:
    """조용히 다른 걸로 대체되면 안 된다."""
    monkeypatch.setenv("MODEL_PROFILE", "local")
    with pytest.raises(NotImplementedError):
        get_client()


def test_모르는_프로필은_거부한다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROFILE", "gemini")
    with pytest.raises(ValueError, match="모르는"):
        get_client()
