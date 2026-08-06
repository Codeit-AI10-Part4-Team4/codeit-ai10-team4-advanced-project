"""정보 등록 — 저장하고 다시 불러올 수 있는지 검증한다."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app_core import store
from app_core.store import JsonProfileStore

ADDR = "서울시 마포구 연남동 1-2"


@pytest.fixture
def db(tmp_path: Path) -> JsonProfileStore:
    """테스트마다 빈 저장소. 실제 data/ 를 건드리지 않는다."""
    return JsonProfileStore(tmp_path)


def test_등록한_정보를_다시_불러온다(db: JsonProfileStore) -> None:
    store.register("sess-1", CAFE := "cafe", ADDR, name="○○카페", store=db)
    got = store.get("sess-1", store=db)
    assert got is not None
    assert got.industry == CAFE and got.name == "○○카페"


def test_등록하지_않았으면_None(db: JsonProfileStore) -> None:
    """처음 온 사장님. 이때 등록 화면을 띄운다."""
    assert store.get("처음온사람", store=db) is None


def test_세션이_다르면_서로_안_보인다(db: JsonProfileStore) -> None:
    store.register("sess-1", "cafe", ADDR, store=db)
    store.register("sess-2", "salon", "서울시 강남구 대치동", store=db)
    a, b = store.get("sess-1", store=db), store.get("sess-2", store=db)
    assert a is not None and b is not None
    assert (a.industry, b.industry) == ("cafe", "salon")


def test_다시_등록하면_덮어쓴다(db: JsonProfileStore) -> None:
    """업종을 잘못 골랐을 때 고칠 수 있어야 한다."""
    store.register("sess-1", "cafe", ADDR, store=db)
    store.register("sess-1", "restaurant", ADDR, store=db)
    got = store.get("sess-1", store=db)
    assert got is not None and got.industry == "restaurant"


def test_틀린_값은_저장되지_않는다(db: JsonProfileStore) -> None:
    """검증 실패 시 파일이 생기면 안 된다."""
    with pytest.raises(ValidationError):
        store.register("sess-1", "우주정거장", ADDR, store=db)
    assert store.get("sess-1", store=db) is None


@pytest.mark.parametrize("bad", ["../evil", "..", "/", ""])
def test_이상한_세션_id는_다른_경로를_건드리지_못한다(db: JsonProfileStore, bad: str) -> None:
    """session_id 는 쿠키에서 온다 — 그대로 파일 경로에 쓰면 위험하다."""
    try:
        store.register(bad, "cafe", ADDR, store=db)
    except ValueError:
        return
    saved = list(db.root.glob("*.json"))
    assert len(saved) == 1
    assert saved[0].parent == db.root


def test_넘길_때는_dict(db: JsonProfileStore) -> None:
    p = store.register("sess-1", "cafe", ADDR, phone="02-000-0000", store=db)
    d = store.as_dict(p)
    assert d["industry"] == "cafe" and d["phone"] == "02-000-0000"
