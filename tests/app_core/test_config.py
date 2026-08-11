""".env 읽기."""

from pathlib import Path

import pytest

from app_core.config import load_env


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_값을_환경변수로_넣는다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADS_TEST_KEY", raising=False)
    load_env(write(tmp_path, "ADS_TEST_KEY=abc123"))
    import os

    assert os.environ["ADS_TEST_KEY"] == "abc123"


def test_이미_있는_값은_안_덮어쓴다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """compose 가 넣은 값이 .env 보다 우선해야 한다."""
    import os

    monkeypatch.setenv("ADS_TEST_KEY", "먼저있던값")
    load_env(write(tmp_path, "ADS_TEST_KEY=나중값"))
    assert os.environ["ADS_TEST_KEY"] == "먼저있던값"


def test_주석과_빈_줄은_건너뛴다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.delenv("ADS_TEST_KEY", raising=False)
    load_env(write(tmp_path, "# 주석\n\nADS_TEST_KEY=값\n"))
    assert os.environ["ADS_TEST_KEY"] == "값"


def test_따옴표를_벗긴다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.delenv("ADS_TEST_KEY", raising=False)
    load_env(write(tmp_path, 'ADS_TEST_KEY="따옴표값"'))
    assert os.environ["ADS_TEST_KEY"] == "따옴표값"


def test_값에_등호가_있어도_된다(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL 이나 키에 = 가 들어갈 수 있다."""
    import os

    monkeypatch.delenv("ADS_TEST_KEY", raising=False)
    load_env(write(tmp_path, "ADS_TEST_KEY=a=b=c"))
    assert os.environ["ADS_TEST_KEY"] == "a=b=c"


def test_파일이_없어도_안_터진다(tmp_path: Path) -> None:
    load_env(tmp_path / "없는파일")
