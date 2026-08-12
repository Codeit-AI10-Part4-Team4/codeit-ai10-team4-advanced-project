"""결과 보관함 테스트 — 임시 폴더에 저장해 실제 data/ 를 건드리지 않는다."""

from pathlib import Path

import pytest
from PIL import Image

from app_core import result_store


def test_save_and_load_result(tmp_path, monkeypatch):
    monkeypatch.setattr(result_store, "_RESULTS", tmp_path / "results")
    img = Image.new("RGB", (32, 32), (10, 20, 30))

    path = result_store.save_result(img)

    assert Path(path).exists()
    assert result_store.load_result(path).size == (32, 32)


def test_load_result_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        result_store.load_result(str(tmp_path / "없는파일.png"))
