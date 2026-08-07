"""주문서 저장과 이력 조회."""

from app_core import ads, stores
from app_core.schema import AdBrief, CopyCandidate, Store, StoreInput


def brief(**kw) -> AdBrief:
    return AdBrief(**{"goal": "copy", "product": "크로플", "price": 4500, **kw})


def test_저장하면_이력에_뜬다(store: Store) -> None:
    ads.save(store.id, brief())
    assert [a.product for a in ads.recent(store.id)] == ["크로플"]


def test_최근_것이_먼저_온다(store: Store) -> None:
    ads.save(store.id, brief(product="크로플"))
    ads.save(store.id, brief(product="아메리카노"))
    assert [a.product for a in ads.recent(store.id)] == ["아메리카노", "크로플"]


def test_이력_개수를_제한한다(store: Store) -> None:
    """프롬프트가 무한정 길어지면 안 된다."""
    for i in range(10):
        ads.save(store.id, brief(product=f"메뉴{i}"))
    assert len(ads.recent(store.id, limit=3)) == 3


def test_처음이면_이력이_비어있다(store: Store) -> None:
    assert ads.recent(store.id) == []


def test_다른_가게_이력은_안_섞인다(user_id: int, store: Store) -> None:
    other = stores.add(user_id, StoreInput(industry="korean_food", name="연남 삼겹살"))
    ads.save(store.id, brief(product="크로플"))
    assert ads.recent(other.id) == []


def test_문구도_함께_저장한다(store: Store) -> None:
    ad_id = ads.save(store.id, brief(), [CopyCandidate(headline="겨울 크로플", sub="4,500원")])
    assert ads.choose_copy(ad_id, "겨울 크로플") is True


def test_없는_문구를_고르면_False(store: Store) -> None:
    ad_id = ads.save(store.id, brief(), [CopyCandidate(headline="겨울 크로플")])
    assert ads.choose_copy(ad_id, "없는 문구") is False


def test_이미지는_경로만_남긴다(store: Store) -> None:
    """파일 자체는 스토리지에 있다 — DB 에 넣으면 금방 커진다."""
    ad_id = ads.save(store.id, brief(goal="image"))
    ads.add_image(ad_id, "gs://bucket/ads/1.png")


def test_원문도_저장되고_다시_읽힌다(store: Store) -> None:
    said = ["단골분들이 매콤한 걸 좋아해요", "젊은 손님도 왔으면 좋겠어요"]
    ads.save(store.id, brief(transcript=said))
    assert ads.recent(store.id)[0].transcript == said


def test_원문이_없어도_읽힌다(store: Store) -> None:
    ads.save(store.id, brief())
    assert ads.recent(store.id)[0].transcript == []


def test_가게를_지우면_이력도_지워진다(user_id: int, store: Store) -> None:
    ads.save(store.id, brief())
    stores.delete(user_id, store.id)
    assert ads.recent(store.id) == []
