"""사진 보관함 — 파일로 두고 번호만 주고받는다."""

from pathlib import Path

import pytest

from app_core import photo_store

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def photo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "photos"
    monkeypatch.setenv("ADS_PHOTO_DIR", str(folder))
    return folder


def test_저장하면_번호를_준다() -> None:
    assert photo_store.save(PNG, "크로플.png") == 1


def test_번호는_1부터_늘어난다() -> None:
    assert [photo_store.save(PNG, "a.png"), photo_store.save(PNG, "b.jpg")] == [1, 2]


def test_번호로_다시_읽는다() -> None:
    photo_id = photo_store.save(PNG, "크로플.png")
    assert photo_store.load(photo_id) == (PNG, "image/png")


def test_확장자에_맞는_mime_을_준다() -> None:
    photo_id = photo_store.save(PNG, "사진.JPG")
    loaded = photo_store.load(photo_id)
    assert loaded is not None and loaded[1] == "image/jpeg"


def test_없는_번호는_None() -> None:
    assert photo_store.load(999) is None
    assert photo_store.path_of(999) is None


def test_보관함_폴더가_아직_없어도_안_터진다() -> None:
    assert photo_store.path_of(1) is None


def test_중간_파일을_지워도_번호가_겹치지_않는다(photo_dir: Path) -> None:
    """개수로 세면 여기서 2 가 다시 나와 남의 사진을 덮어쓴다."""
    photo_store.save(PNG, "a.png")
    second = photo_store.save(PNG, "b.png")
    photo_store.save(PNG, "c.png")

    path = photo_store.path_of(second)
    assert path is not None
    path.unlink()

    assert photo_store.save(PNG, "d.png") == 4


def test_지원하지_않는_형식은_막는다() -> None:
    with pytest.raises(ValueError, match="지원하지 않는"):
        photo_store.save(PNG, "문서.pdf")


def test_확장자가_없어도_막는다() -> None:
    with pytest.raises(ValueError):
        photo_store.save(PNG, "사진")


def test_빈_파일은_막는다() -> None:
    with pytest.raises(ValueError, match="빈 파일"):
        photo_store.save(b"", "a.png")


def test_너무_큰_사진은_막는다() -> None:
    with pytest.raises(ValueError, match="너무 큽니다"):
        photo_store.save(b"0" * (photo_store.MAX_BYTES + 1), "a.png")
