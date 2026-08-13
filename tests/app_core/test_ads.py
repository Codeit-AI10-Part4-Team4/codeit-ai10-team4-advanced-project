"""주문서 저장과 이력 조회."""

from sqlalchemy import select

from app_core import ads, db, stores
from app_core.schema import AdBrief, CopyCandidate, Feedback, Store, StoreInput


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
    assert ads.choose_copy(store.id, ad_id, "겨울 크로플") is True


def test_없는_문구를_고르면_False(store: Store) -> None:
    ad_id = ads.save(store.id, brief(), [CopyCandidate(headline="겨울 크로플")])
    assert ads.choose_copy(store.id, ad_id, "없는 문구") is False


def test_이미지는_경로만_남긴다(store: Store) -> None:
    """파일 자체는 스토리지에 있다 — DB 에 넣으면 금방 커진다."""
    ad_id = ads.save(store.id, brief(goal="image"))
    assert ads.add_image(store.id, ad_id, "gs://bucket/ads/1.png") is True


def test_원문도_저장되고_다시_읽힌다(store: Store) -> None:
    said = ["단골분들이 매콤한 걸 좋아해요", "젊은 손님도 왔으면 좋겠어요"]
    ads.save(store.id, brief(transcript=said))
    assert ads.recent(store.id)[0].transcript == said


def test_원문이_없어도_읽힌다(store: Store) -> None:
    ads.save(store.id, brief())
    assert ads.recent(store.id)[0].transcript == []


def test_사진_번호도_저장되고_다시_읽힌다(store: Store) -> None:
    ads.save(store.id, brief(goal="image", photo_id=7))
    assert ads.recent(store.id)[0].photo_id == 7


def test_사진이_없으면_None으로_읽힌다(store: Store) -> None:
    ads.save(store.id, brief())
    assert ads.recent(store.id)[0].photo_id is None


def test_레퍼런스와_스케치도_따로_저장된다(store: Store) -> None:
    """받는 쪽이 칸을 보고 무엇을 할지 정한다 — 섞이면 안 된다."""
    ads.save(store.id, brief(goal="image", photo_id=7, ref_id=8, sketch_id=9))
    saved = ads.recent(store.id)[0]
    assert (saved.photo_id, saved.ref_id, saved.sketch_id) == (7, 8, 9)


def test_사진에서_읽은_메모도_같이_저장된다(store: Store) -> None:
    """다시 만들 때 사진을 또 읽지 않으려고 남긴다."""
    note = "- 찍힌 것: 크로플\n- 사진의 분위기: 따뜻하고 아늑한"
    ads.save(store.id, brief(photo_id=7, photo_note=note))
    assert ads.recent(store.id)[0].photo_note == note


# ── 다시 만들기 ──────────────────────────────────────────────


def test_만든_문구를_다시_꺼낼_수_있다(store: Store) -> None:
    """다시 만들 때 '이것과 다르게'로 넣으려면 꺼낼 수 있어야 한다."""
    made = [CopyCandidate(headline="겨울 크로플", sub="4,500원"), CopyCandidate(headline="따끈")]
    ad_id = ads.save(store.id, brief(), made)
    assert ads.copies_of(store.id, ad_id) == made


def test_문구가_없으면_빈_목록(store: Store) -> None:
    assert ads.copies_of(store.id, ads.save(store.id, brief())) == []


def test_다시_만들면_직전_것을_덮어쓰지_않는다(store: Store) -> None:
    """사장님이 "아까 그게 나았는데" 할 때 돌아갈 곳이 있어야 한다."""
    first = ads.save(store.id, brief())
    second = ads.save(store.id, brief(), parent_id=first)
    assert first != second
    assert len(ads.recent(store.id)) == 2


def test_재생성_이유가_저장된다(store: Store) -> None:
    fb = Feedback(source="typed", notes=["좀 더 밝게"])
    ad_id = ads.save(store.id, brief().revised(fb, []))
    with db.session() as s:
        row = s.get(db.AdRow, ad_id)
        assert row is not None
        assert row.feedback_source == "typed"
        assert row.feedback_notes == "좀 더 밝게"


def test_처음_만든_것은_이유가_비어있다(store: Store) -> None:
    with db.session() as s:
        row = s.get(db.AdRow, ads.save(store.id, brief()))
        assert row is not None
        assert row.feedback_source == "" and row.parent_id is None


def test_패널_평가로_다시_만든_것도_저장된다(store: Store) -> None:
    fb = Feedback(source="panel", notes=["묶음가로 제시", "가격을 크게"], resistance=["가격"])
    ad_id = ads.save(store.id, brief().revised(fb, []))
    with db.session() as s:
        row = s.get(db.AdRow, ad_id)
        assert row is not None
        assert row.feedback_source == "panel"
        assert row.feedback_notes == "묶음가로 제시\n가격을 크게"


def test_가게를_지우면_이력도_지워진다(user_id: int, store: Store) -> None:
    ads.save(store.id, brief())
    stores.delete(user_id, store.id)
    assert ads.recent(store.id) == []


# ── 남의 광고 ────────────────────────────────────────────────
#
# 광고 번호만 알면 남의 광고를 읽고 고칠 수 있으면 안 된다.
# 지금 화면에서는 번호가 세션에서만 와서 도달할 길이 없지만, 저장소 안에서
# 규칙이 갈리면 API 를 붙이는 사람이 어느 쪽이 맞는지 알 수 없다.


def other_store(user_id: int) -> Store:
    return stores.add(user_id, StoreInput(industry="korean_food", name="옆집 삼겹살"))


def test_남의_광고_문구는_안_보인다(user_id: int, store: Store) -> None:
    ad_id = ads.save(store.id, brief(), [CopyCandidate(headline="겨울 크로플")])
    assert ads.copies_of(other_store(user_id).id, ad_id) == []


def test_없는_광고와_남의_광고는_같은_답을_준다(user_id: int, store: Store) -> None:
    """답이 갈리면 번호를 넣어보는 것만으로 남의 광고가 있는지 알 수 있다."""
    ad_id = ads.save(store.id, brief(), [CopyCandidate(headline="겨울 크로플")])
    mine = other_store(user_id).id
    assert ads.copies_of(mine, ad_id) == ads.copies_of(mine, 999999) == []


def test_남의_광고_문구는_못_고른다(user_id: int, store: Store) -> None:
    ad_id = ads.save(store.id, brief(), [CopyCandidate(headline="겨울 크로플")])
    assert ads.choose_copy(other_store(user_id).id, ad_id, "겨울 크로플") is False


def test_막힌_선택은_흔적을_안_남긴다(user_id: int, store: Store) -> None:
    """False 만 돌려주고 실제로는 바꿔놨으면 막은 게 아니다."""
    ad_id = ads.save(store.id, brief(), [CopyCandidate(headline="겨울 크로플")])
    ads.choose_copy(other_store(user_id).id, ad_id, "겨울 크로플")
    with db.session() as s:
        rows = s.scalars(select(db.CopyRow).where(db.CopyRow.ad_id == ad_id)).all()
        assert all(r.chosen == 0 for r in rows)


def test_남의_광고에는_이미지를_못_붙인다(user_id: int, store: Store) -> None:
    ad_id = ads.save(store.id, brief(goal="image"))
    assert ads.add_image(other_store(user_id).id, ad_id, "gs://bucket/1.png") is False
    with db.session() as s:
        assert s.scalars(select(db.ImageRow).where(db.ImageRow.ad_id == ad_id)).all() == []


def test_없는_광고에도_안_붙는다(store: Store) -> None:
    assert ads.add_image(store.id, 999999, "gs://bucket/1.png") is False
