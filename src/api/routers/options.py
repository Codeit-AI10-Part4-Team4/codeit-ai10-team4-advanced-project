"""선택지 라우터.

자연어로 말하기 어려운 사장님을 위해 화면에 띄우는 목록.
목록이 레지스트리에서 나오므로, 화면의 선택지와 검증이 어긋날 수 없다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app_core import registry

router = APIRouter(tags=["options"])

KINDS = ("industries", "styles", "formats")


@router.get("/options/{kind}")
def get_options(kind: str) -> list[dict[str, str]]:
    """`industries` | `styles` | `formats` 의 선택지."""
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail=f"없는 목록입니다: {kind}")
    return registry.options(kind)
