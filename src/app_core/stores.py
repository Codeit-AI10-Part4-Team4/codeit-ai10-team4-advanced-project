"""가게 관리 — 목록·추가·수정·삭제.

한 사용자가 여러 가게를 가진다. 광고를 만들기 전에 어느 가게인지 고른다.
"""

from __future__ import annotations

from sqlalchemy import select

from app_core import db
from app_core.schema import Store, StoreInput


def _to_schema(row: db.StoreRow) -> Store:
    return Store(
        id=row.id,
        user_id=row.user_id,
        industry=row.industry,
        name=row.name,
        address=row.address,
        phone=row.phone,
        industry_note=row.industry_note,
    )


def list_stores(user_id: int) -> list[Store]:
    """내 가게 목록. 먼저 등록한 것이 위로 온다."""
    with db.session() as s:
        rows = s.scalars(
            select(db.StoreRow).where(db.StoreRow.user_id == user_id).order_by(db.StoreRow.id)
        ).all()
        return [_to_schema(r) for r in rows]


def get(user_id: int, store_id: int) -> Store | None:
    """남의 가게를 못 열도록 user_id 까지 대조한다."""
    with db.session() as s:
        row = s.scalar(
            select(db.StoreRow).where(db.StoreRow.id == store_id, db.StoreRow.user_id == user_id)
        )
        return _to_schema(row) if row else None


def add(user_id: int, data: StoreInput) -> Store:
    """가게를 추가한다. 값 검증은 StoreInput 이 이미 끝냈다."""
    with db.session() as s:
        row = db.StoreRow(user_id=user_id, **data.model_dump())
        s.add(row)
        s.flush()
        return _to_schema(row)


def update(user_id: int, store_id: int, data: StoreInput) -> Store | None:
    """가게 정보를 고친다. 없거나 남의 것이면 None."""
    with db.session() as s:
        row = s.scalar(
            select(db.StoreRow).where(db.StoreRow.id == store_id, db.StoreRow.user_id == user_id)
        )
        if row is None:
            return None
        for field, value in data.model_dump().items():
            setattr(row, field, value)
        s.flush()
        return _to_schema(row)


def delete(user_id: int, store_id: int) -> bool:
    """가게와 그 광고 이력까지 함께 지운다 (cascade)."""
    with db.session() as s:
        row = s.scalar(
            select(db.StoreRow).where(db.StoreRow.id == store_id, db.StoreRow.user_id == user_id)
        )
        if row is None:
            return False
        s.delete(row)
        return True
