"""테스트 공통 준비.

두 갈래의 픽스처가 함께 있다.

- **서비스(로그인·가게·주문서)**: 실제 PostgreSQL 대신 임시 SQLite 파일을 쓴다 —
  테스트마다 빈 DB 로 시작하고, CI 에 DB 서버가 없어도 돌아간다.
- **패널 평가**: `features_yeoksam_20261.json` 은 A(패널 구성) 담당이 CSV 실물
  검수 후 만든 역삼역 2026Q1 실측 산출물이다. 계약이 깨지면 여기서 먼저 터지도록
  골든 픽스처로 쓴다. 아인님 소유 파일이라 수정하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app_core import db
from app_core.panel.schemas import Panel
from app_core.schema import Store

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# `eval/` 은 src 레이아웃 밖이라 설치 대상이 아니다. 예전에는 여기서 sys.path 를
# 건드렸는데, `pyproject.toml` 의 [tool.pytest.ini_options] pythonpath 로 옮겼다.
# 그래야 `pytest` 로 돌리든 `python -m pytest` 로 돌리든 똑같이 동작한다.


# --- 서비스 ---------------------------------------------------------------


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


# --- 패널 평가 -------------------------------------------------------------


@pytest.fixture(scope="session")
def yeoksam_raw() -> dict[str, Any]:
    with (FIXTURE_DIR / "features_yeoksam_20261.json").open(encoding="utf-8") as fp:
        data: dict[str, Any] = json.load(fp)
    return data


@pytest.fixture
def yeoksam(yeoksam_raw: dict[str, Any]) -> Panel:
    return Panel.model_validate(yeoksam_raw)
