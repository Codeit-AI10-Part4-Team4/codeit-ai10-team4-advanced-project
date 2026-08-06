"""가게 관리 — 한 사용자가 여러 가게를 가진다."""

from app_core import auth, stores
from app_core.schema import Store, StoreInput


def form(**kw) -> StoreInput:
    return StoreInput(**{"industry": "cafe", "name": "연남 크로플", **kw})


def test_추가한_가게가_목록에_뜬다(user_id: int) -> None:
    stores.add(user_id, form())
    assert [s.name for s in stores.list_stores(user_id)] == ["연남 크로플"]


def test_여러_가게를_가질_수_있다(user_id: int) -> None:
    """여러 업장을 운영하는 사장님이 있다."""
    stores.add(user_id, form(name="연남 크로플"))
    stores.add(user_id, form(industry="korean_food", name="연남 삼겹살"))
    assert len(stores.list_stores(user_id)) == 2


def test_처음이면_목록이_비어있다(user_id: int) -> None:
    assert stores.list_stores(user_id) == []


def test_가게를_고칠_수_있다(user_id: int, store: Store) -> None:
    updated = stores.update(user_id, store.id, form(name="연남 크로플 2호점"))
    assert updated is not None and updated.name == "연남 크로플 2호점"


def test_가게를_지울_수_있다(user_id: int, store: Store) -> None:
    assert stores.delete(user_id, store.id) is True
    assert stores.list_stores(user_id) == []


def test_남의_가게는_안_보인다(user_id: int, store: Store) -> None:
    other = auth.signup("남의사장님", "password123")
    assert stores.get(other, store.id) is None
    assert stores.list_stores(other) == []


def test_남의_가게는_못_고친다(user_id: int, store: Store) -> None:
    other = auth.signup("남의사장님", "password123")
    assert stores.update(other, store.id, form(name="빼앗기")) is None


def test_남의_가게는_못_지운다(user_id: int, store: Store) -> None:
    other = auth.signup("남의사장님", "password123")
    assert stores.delete(other, store.id) is False


def test_없는_가게를_조회하면_None(user_id: int) -> None:
    assert stores.get(user_id, 9999) is None


def test_기타_업종도_저장되고_다시_읽힌다(user_id: int) -> None:
    stores.add(user_id, form(industry="other", industry_note="드라이플라워 공방"))
    saved = stores.list_stores(user_id)[0]
    assert saved.industry_label == "드라이플라워 공방"
