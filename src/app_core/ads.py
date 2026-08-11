"""주문서·생성 결과 저장과 이력 조회.

이력을 남기는 이유는 다음 생성 때 참고하기 위해서다. 지금은 최근 몇 건을
프롬프트에 넣는 방식이고, 이력이 많이 쌓이면 벡터 검색으로 바꾼다.
"""

from __future__ import annotations

from sqlalchemy import select

from app_core import db
from app_core.schema import AdBrief, CopyCandidate

RECENT_LIMIT = 5


def _to_brief(row: db.AdRow) -> AdBrief:
    return AdBrief(
        goal=row.goal,  # type: ignore[arg-type]  # DB 에는 image/copy 만 들어간다
        product=row.product,
        price=row.price,
        situation=row.situation,
        tone=row.tone,
        extra=row.extra,
        photo_id=row.photo_id,
        transcript=row.transcript.split("\n") if row.transcript else [],
    )


def save(
    store_id: int,
    brief: AdBrief,
    copies: list[CopyCandidate] | None = None,
    parent_id: int | None = None,
) -> int:
    """주문서와 생성된 문구를 저장하고 광고 id 를 돌려준다.

    다시 만든 것이면 parent_id 로 직전 광고를 가리킨다. 덮어쓰지 않는 이유는
    사장님이 "아까 그게 나았는데" 할 때 돌아갈 곳이 있어야 하기 때문이다.
    """
    fb = brief.feedback
    with db.session() as s:
        row = db.AdRow(
            store_id=store_id,
            goal=brief.goal,
            product=brief.product,
            price=brief.price,
            situation=brief.situation,
            tone=brief.tone,
            extra=brief.extra,
            photo_id=brief.photo_id,
            transcript=brief.raw_utterance,
            parent_id=parent_id,
            feedback_source=fb.source if fb else "",
            feedback_notes="\n".join(fb.notes) if fb else "",
        )
        s.add(row)
        s.flush()
        for c in copies or []:
            s.add(db.CopyRow(ad_id=row.id, headline=c.headline, sub=c.sub))
        return row.id


def copies_of(ad_id: int) -> list[CopyCandidate]:
    """그 광고로 만든 문구들. 다시 만들 때 '이것과 다르게'로 넣는다."""
    with db.session() as s:
        rows = s.scalars(
            select(db.CopyRow).where(db.CopyRow.ad_id == ad_id).order_by(db.CopyRow.id)
        ).all()
        return [CopyCandidate(headline=r.headline, sub=r.sub) for r in rows]


def choose_copy(ad_id: int, headline: str) -> bool:
    """사장님이 고른 문구를 표시한다. 어떤 문구가 선택받는지 보려고 남긴다."""
    with db.session() as s:
        rows = s.scalars(select(db.CopyRow).where(db.CopyRow.ad_id == ad_id)).all()
        found = False
        for row in rows:
            row.chosen = 1 if row.headline == headline else 0
            found = found or row.chosen == 1
        return found


def add_image(ad_id: int, path: str) -> None:
    """생성된 이미지 경로를 남긴다. 파일 자체는 스토리지에 있다."""
    with db.session() as s:
        s.add(db.ImageRow(ad_id=ad_id, path=path))


def recent(store_id: int, limit: int = RECENT_LIMIT) -> list[AdBrief]:
    """이 가게가 최근에 만든 광고. 문구 생성 프롬프트에 넣는다."""
    with db.session() as s:
        rows = s.scalars(
            select(db.AdRow)
            .where(db.AdRow.store_id == store_id)
            .order_by(db.AdRow.created_at.desc(), db.AdRow.id.desc())
            .limit(limit)
        ).all()
        return [_to_brief(r) for r in rows]
