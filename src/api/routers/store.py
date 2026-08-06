"""가게 정보 등록 라우터.

라우터는 얇게: 세션 확인 → app_core 호출 → 응답 변환.
검증은 StoreProfile 이 한다 — 요청 본문 모델로 그대로 쓰므로
모르는 업종·서울 밖 주소는 FastAPI 가 422 로 돌려준다.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Response

from app_core import store
from app_core.schema import StoreProfile

router = APIRouter(tags=["store"])

SESSION_COOKIE = "session_id"
# 로그인이 없다. 브라우저를 닫아도 등록 정보를 다시 쓸 수 있도록 30일.
SESSION_MAX_AGE = 60 * 60 * 24 * 30


def _session(response: Response, session_id: str | None) -> str:
    """세션 쿠키를 읽고, 없으면 새로 발급한다."""
    if session_id:
        return session_id
    new_id = uuid.uuid4().hex
    response.set_cookie(
        SESSION_COOKIE, new_id, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax"
    )
    return new_id


@router.get("/store", response_model=StoreProfile)
def get_store(
    response: Response,
    session_id: Annotated[str | None, Cookie()] = None,
) -> StoreProfile:
    """등록된 가게 정보. 처음 온 사장님이면 404 → 등록 화면을 띄운다."""
    profile = store.get(_session(response, session_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="등록된 가게 정보가 없습니다")
    return profile


@router.put("/store", response_model=StoreProfile)
def put_store(
    profile: StoreProfile,
    response: Response,
    session_id: Annotated[str | None, Cookie()] = None,
) -> StoreProfile:
    """가게 정보를 등록하거나 고친다. 같은 세션이면 덮어쓴다."""
    return store.register(
        _session(response, session_id),
        industry=profile.industry,
        address=profile.address,
        name=profile.name,
        phone=profile.phone,
    )
