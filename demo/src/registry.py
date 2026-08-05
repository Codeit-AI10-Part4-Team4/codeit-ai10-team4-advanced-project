"""설정 레지스트리 로더.

업종·스타일·규격·법령·금칙어를 YAML 에서 읽는다.
코드에 하드코딩된 업종 목록이 존재하지 않게 하는 것이 목적.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


@lru_cache(maxsize=None)
def _load(name: str) -> tuple[dict[str, Any], ...]:
    path = CONFIG_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return tuple(data)


def industries() -> list[dict]:
    return list(_load("industries"))


def styles() -> list[dict]:
    return list(_load("styles"))


def formats() -> list[dict]:
    return list(_load("formats"))


def laws() -> list[dict]:
    return list(_load("laws"))


def banned_terms() -> list[dict]:
    return list(_load("banned_terms"))


def by_id(items: list[dict], item_id: str) -> dict:
    for it in items:
        if it["id"] == item_id:
            return it
    raise KeyError(f"'{item_id}' 를 레지스트리에서 찾을 수 없습니다.")


def legal_tags_for(industry: dict, fmt: dict) -> set[str]:
    """업종 태그 ∪ 규격 태그.

    이 집합으로 적용 법령과 금칙어 규칙의 검색 범위를 사전 축소한다.
    예) 카페(food, general) × 전단지(offline, outdoor)
        → 학원법·체육시설법은 애초에 검토 대상에서 제외된다.
    """
    return set(industry.get("legal_tags", [])) | set(fmt.get("legal_tags", []))
