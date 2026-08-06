"""업종 목록.

가게 등록 화면의 업종 선택지이자, 저장 전 검증 기준이다.
목록을 코드가 아니라 configs/industries.yaml 에 둬서 업종을 추가할 때
코드를 고치지 않아도 되게 한다.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

# src/app_core/registry.py → parents[2] 가 저장소 루트.
# 배포 환경에서 경로가 다르면 ADS_CONFIG_DIR 로 덮어쓴다.
CONFIG_DIR = Path(
    os.environ.get("ADS_CONFIG_DIR") or Path(__file__).resolve().parents[2] / "configs"
)


@cache
def _load(name: str) -> tuple[dict[str, Any], ...]:
    with (CONFIG_DIR / f"{name}.yaml").open(encoding="utf-8") as f:
        return tuple(yaml.safe_load(f) or [])


# 목록에 없는 업종. 사장님이 직접 적은 값을 대신 쓴다.
OTHER = "other"


def industries() -> list[dict]:
    return list(_load("industries"))


def industry_ids() -> set[str]:
    return {i["id"] for i in _load("industries")}


def industry_options() -> list[dict[str, str]]:
    """선택지로 보여줄 최소 정보만 추린다.

    프롬프트용 필드까지 화면에 내려보내면 바뀔 때마다 프론트가 같이 흔들린다.
    """
    return [
        {"id": i["id"], "label": i["label"], "emoji": i.get("emoji", "")}
        for i in _load("industries")
    ]


def label_of(industry_id: str) -> str:
    """프롬프트에 넣을 사람이 읽는 이름 — 예: cafe → 카페·디저트."""
    for i in _load("industries"):
        if i["id"] == industry_id:
            return str(i["label"])
    raise KeyError(f"'{industry_id}' 를 업종 목록에서 찾을 수 없습니다.")
