"""테스트 공통 준비.

실제 PostgreSQL 대신 임시 SQLite 파일을 쓴다 — 테스트마다 빈 DB 로 시작하고,
CI 에 DB 서버가 없어도 돌아간다.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app_core import db
from app_core.schema import Store


@pytest.fixture(autouse=True)
def clean_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    db.reset()
    yield
    db.reset()


@pytest.fixture
def user_id() -> int:
    from app_core import auth

    return auth.signup("사장님", "password123")


@pytest.fixture
def store(user_id: int) -> Store:
    from app_core import stores
    from app_core.schema import StoreInput

    return stores.add(
        user_id,
        StoreInput(industry="cafe", name="연남 크로플", address="서울시 마포구 연남동 1-2"),
    )
