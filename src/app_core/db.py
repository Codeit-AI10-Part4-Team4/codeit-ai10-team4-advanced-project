"""DB 연결과 테이블 정의 — PostgreSQL.

DATABASE_URL 로 접속 대상을 바꾼다.
  운영·개발  postgresql+psycopg://user:pw@host/db
  테스트     sqlite://  (메모리)

SQLAlchemy 를 쓰는 이유는 테스트에서 SQLite 로 바꿔치기하기 위해서다.
실제 대상은 PostgreSQL 이고, 나중에 pgvector 를 붙이는 것도 여기서 한다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

DEFAULT_URL = "postgresql+psycopg://ads:ads@localhost:5432/ads"


def database_url() -> str:
    """호출할 때마다 읽는다 — import 시점에 고정하면 테스트에서 못 바꾼다."""
    return os.environ.get("DATABASE_URL") or DEFAULT_URL


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    stores: Mapped[list[StoreRow]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class StoreRow(Base):
    """가게. 한 사용자가 여러 개를 가진다 — 여러 업장을 운영하는 사장님이 있다."""

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    industry: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    address: Mapped[str] = mapped_column(String(256))
    phone: Mapped[str] = mapped_column(String(32), default="")
    # industry 가 other 일 때 사장님이 직접 적은 업종명
    industry_note: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped[User] = relationship(back_populates="stores")
    ads: Mapped[list[AdRow]] = relationship(back_populates="store", cascade="all, delete-orphan")


class AdRow(Base):
    """완성된 주문서 한 건. 다음 생성 때 참고할 이력이기도 하다."""

    __tablename__ = "ads"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    goal: Mapped[str] = mapped_column(String(16))
    product: Mapped[str] = mapped_column(String(128))
    price: Mapped[int] = mapped_column(Integer, default=0)
    situation: Mapped[str] = mapped_column(String(128), default="")
    tone: Mapped[str] = mapped_column(String(128), default="")
    extra: Mapped[str] = mapped_column(Text, default="")
    # 사진 보관함 번호 셋. 파일 자체는 photo_store 가 들고 있다.
    # 용도가 달라서 칸을 나눴다 — 살릴 사진 / 참고할 사진 / 따라갈 구도.
    photo_id: Mapped[int | None] = mapped_column(Integer, default=None)
    ref_id: Mapped[int | None] = mapped_column(Integer, default=None)
    sketch_id: Mapped[int | None] = mapped_column(Integer, default=None)
    #: 제품 사진을 비전 모델로 읽은 메모. 사장님이 한 말이 아니라 사진에서 본 것이다
    photo_note: Mapped[str] = mapped_column(Text, default="")
    # 사장님이 한 말 원문. 줄바꿈으로 이어 붙인다.
    # 슬롯으로 요약하면서 깎인 뉘앙스를 여기서 되살린다.
    transcript: Mapped[str] = mapped_column(Text, default="")

    # 다시 만든 것이면 직전 광고를 가리킨다. 사슬을 따라가면 수정 이력이 나온다.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("ads.id", ondelete="SET NULL"), default=None, index=True
    )
    #: "" | typed | option | panel — 어느 경로로 다시 만들었는지
    feedback_source: Mapped[str] = mapped_column(String(16), default="")
    feedback_notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    store: Mapped[StoreRow] = relationship(back_populates="ads")
    copies: Mapped[list[CopyRow]] = relationship(back_populates="ad", cascade="all, delete-orphan")
    images: Mapped[list[ImageRow]] = relationship(back_populates="ad", cascade="all, delete-orphan")


class CopyRow(Base):
    """생성된 문구. 후보 3건이 한 주문서에 달린다."""

    __tablename__ = "ad_copies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ads.id", ondelete="CASCADE"), index=True)
    headline: Mapped[str] = mapped_column(String(128))
    sub: Mapped[str] = mapped_column(String(256), default="")
    chosen: Mapped[int] = mapped_column(Integer, default=0, comment="사장님이 고른 것이면 1")

    ad: Mapped[AdRow] = relationship(back_populates="copies")


class ImageRow(Base):
    """생성된 이미지.

    ⚠️ 파일 자체는 DB 에 넣지 않는다. 스토리지(GCS 등)에 두고 경로만 남긴다.
    """

    __tablename__ = "ad_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ads.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(512))

    ad: Mapped[AdRow] = relationship(back_populates="images")


# 접속을 매번 새로 만들면 느리다. URL 이 바뀔 때만 다시 만든다.
_connected_url: str | None = None
_Session: sessionmaker[Session] | None = None


def _get_session_factory() -> sessionmaker[Session]:
    global _connected_url, _Session
    url = database_url()
    if _Session is None or _connected_url != url:
        engine = create_engine(url, future=True)
        Base.metadata.create_all(engine)
        _Session = sessionmaker(bind=engine, expire_on_commit=False)
        _connected_url = url
    return _Session


def reset() -> None:
    """DATABASE_URL 을 바꾼 뒤 다시 연결하게 한다 — 테스트에서 쓴다."""
    global _connected_url, _Session
    _connected_url = None
    _Session = None


@contextmanager
def session() -> Iterator[Session]:
    """트랜잭션 하나. 예외가 나면 되돌린다."""
    db = _get_session_factory()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
