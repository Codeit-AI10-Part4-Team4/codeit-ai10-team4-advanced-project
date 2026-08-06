"""업종·스타일·규격 레지스트리.

목록을 코드가 아니라 configs/*.yaml 에 둔다.
업종을 추가할 때 코드를 고치지 않아도 되고, 선택지·검증·프롬프트가 함께 따라온다.
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


def industries() -> list[dict]:
    return list(_load("industries"))


def styles() -> list[dict]:
    return list(_load("styles"))


def formats() -> list[dict]:
    return list(_load("formats"))


def options(kind: str) -> list[dict[str, str]]:
    """선택지로 보여줄 최소 정보만 추린다.

    프롬프트용 필드(scene_prompt 등)까지 화면에 내려보내면
    바뀔 때마다 프론트가 같이 흔들린다.
    """
    return [{"id": i["id"], "label": i["label"], "emoji": i.get("emoji", "")} for i in _load(kind)]


def by_id(items: list[dict], item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise KeyError(f"'{item_id}' 를 레지스트리에서 찾을 수 없습니다.")


def legal_tags_for(industry: dict, fmt: dict) -> set[str]:
    """업종 태그 ∪ 규격 태그.

    규격이 법령을 바꾼다 — 전단지에는 옥외광고물법이 붙고 인스타에는 붙지 않는다.
    """
    return set(industry.get("legal_tags", [])) | set(fmt.get("legal_tags", []))
