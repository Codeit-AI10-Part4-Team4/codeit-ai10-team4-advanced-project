"""주문서·생성 결과 저장과 이력 조회.

이력을 남기는 이유는 다음 생성 때 참고하기 위해서다. 지금은 최근 몇 건을
프롬프트에 넣는 방식이고, 이력이 많이 쌓이면 벡터 검색으로 바꾼다.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

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
        ref_id=row.ref_id,
        sketch_id=row.sketch_id,
        photo_note=row.photo_note,
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
            ref_id=brief.ref_id,
            sketch_id=brief.sketch_id,
            photo_note=brief.photo_note,
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


def _owned(s: Session, store_id: int, ad_id: int) -> db.AdRow | None:
    """이 가게의 광고일 때만 돌려준다. 아니면 None.

    광고 번호만 알면 남의 광고를 읽고 고칠 수 있으면 안 된다. 지금 화면에서는
    번호가 세션에서만 와서 도달할 길이 없지만, 저장소 안에서 규칙이 갈리면
    API 를 붙이는 사람이 어느 쪽이 맞는지 알 수 없다.

    범위를 user 가 아니라 store 로 잡는 이유: 광고는 가게에 달려 있고, 그 가게가
    이 사용자 것인지는 부르기 전에 stores.get(user_id, store_id) 가 이미 본다.
    """
    return s.scalars(
        select(db.AdRow).where(db.AdRow.id == ad_id, db.AdRow.store_id == store_id)
    ).one_or_none()


def copies_of(store_id: int, ad_id: int) -> list[CopyCandidate]:
    """그 광고로 만든 문구들. 다시 만들 때 '이것과 다르게'로 넣는다.

    남의 광고면 빈 목록. 없는 광고와 같은 답을 주는 것은 일부러다 —
    답이 갈리면 번호를 넣어보는 것만으로 남의 광고가 있는지 알 수 있다.
    """
    with db.session() as s:
        if _owned(s, store_id, ad_id) is None:
            return []
        rows = s.scalars(
            select(db.CopyRow).where(db.CopyRow.ad_id == ad_id).order_by(db.CopyRow.id)
        ).all()
        return [CopyCandidate(headline=r.headline, sub=r.sub) for r in rows]


def choose_copy(store_id: int, ad_id: int, headline: str) -> bool:
    """사장님이 고른 문구를 표시한다. 어떤 문구가 선택받는지 보려고 남긴다.

    남의 광고면 아무것도 안 바꾸고 False.
    """
    with db.session() as s:
        if _owned(s, store_id, ad_id) is None:
            return False
        rows = s.scalars(select(db.CopyRow).where(db.CopyRow.ad_id == ad_id)).all()
        found = False
        for row in rows:
            row.chosen = 1 if row.headline == headline else 0
            found = found or row.chosen == 1
        return found


def add_image(store_id: int, ad_id: int, path: str) -> bool:
    """생성된 이미지 경로를 남긴다. 파일 자체는 스토리지에 있다.

    남의 광고면 아무것도 안 남기고 False. 전에는 반환값이 없었는데, 붙었는지
    아닌지를 부르는 쪽이 알 수 있어야 해서 bool 로 바꿨다.
    """
    with db.session() as s:
        if _owned(s, store_id, ad_id) is None:
            return False
        s.add(db.ImageRow(ad_id=ad_id, path=path))
        return True


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
