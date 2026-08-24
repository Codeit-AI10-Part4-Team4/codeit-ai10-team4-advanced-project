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

from app_core import db, gen_background, image_backend
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


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """대역을 빼먹은 테스트의 실제 LLM 호출을 차단한다.

    `tests/test_app_image_flow.py` 와 `tests/test_app_panel_source.py` 가 app.py 를
    import 하는데, app.py 는 최상단에서 `config.load_env()` 를 부른다. 그래서
    **수집 단계에서** .env 의 MODEL_PROFILE=openai 와 OPENAI_API_KEY 가 프로세스
    전체에 실린다. 대역 없이 생성 경로를 타는 테스트가 하나라도 생기면 그대로
    유료 호출이 나간다 — 2026-08-24에 /ads/copies 테스트가 실제로 문구 세 건을
    받아왔다(AGENTS.md 위반).

    아래 no_real_image_backends 와 같은 이유·같은 모양이다. 특정 프로필이
    필요한 테스트는 자기 monkeypatch 로 덮으면 된다(이 픽스처보다 나중에 돈다).
    """
    monkeypatch.setenv("MODEL_PROFILE", "stub")
    # 프로필을 덮어쓰는 테스트가 실수로 실호출을 내지 않도록 키까지 없앤다.
    # 키가 없으면 OpenAI() 생성 자체가 터져서 조용히 과금되는 길이 사라진다.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_real_image_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    """대역을 빼먹은 테스트의 실제 sd-turbo·OpenAI 호출을 차단한다.

    2026-08-19에 옛 대역이 남은 테스트가 sd-turbo를 진짜로 로드한 적이 있다.
    실제 모델이나 API를 부르려 하면 즉시 AssertionError로 막는다.
    """

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("테스트가 실제 이미지 모델/API를 부르려 했습니다 — 대역을 씌우세요")

    # 개발 셸이나 앞서 import 된 app.py가 .env의 openai 프로필을 올려도 기존
    # 테스트가 유료 경로로 새지 않는다.
    monkeypatch.delenv("MODEL_PROFILE", raising=False)
    monkeypatch.delenv("IMAGE_PROFILE", raising=False)
    monkeypatch.setattr(gen_background, "_load_pipe", _boom)
    monkeypatch.setattr(image_backend, "_openai_scene", _boom)
    monkeypatch.setattr(image_backend, "_openai_edit", _boom)
    monkeypatch.setattr(image_backend, "_openai_restage", _boom)
    image_backend.pop_notices()


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
