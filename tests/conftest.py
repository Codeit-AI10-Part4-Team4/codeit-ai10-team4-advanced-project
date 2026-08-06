"""공용 픽스처와 경로 설정.

`features_yeoksam.json`은 A(패널 구성) 담당이 넘겨준 실제 산출물 샘플이다.
계약이 깨지면 여기서 먼저 터지도록 골든 픽스처로 쓴다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app_core.panel.schemas import Panel

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures"

# `eval/`은 src 레이아웃 밖이라 설치 대상이 아니고, 그대로는 import 되지 않는다.
# 공유 설정을 건드리지 않으려고 여기서만 경로를 넣는다.
# → 팀 합의 후 pyproject의 [tool.pytest.ini_options] pythonpath 에 "eval" 을
#   추가하면 아래 두 줄은 지워도 된다.
if str(ROOT / "eval") not in sys.path:
    sys.path.insert(0, str(ROOT / "eval"))


@pytest.fixture(scope="session")
def yeoksam_raw() -> dict[str, Any]:
    with (FIXTURE_DIR / "features_yeoksam.json").open(encoding="utf-8") as fp:
        data: dict[str, Any] = json.load(fp)
    return data


@pytest.fixture
def yeoksam(yeoksam_raw: dict[str, Any]) -> Panel:
    return Panel.model_validate(yeoksam_raw)
