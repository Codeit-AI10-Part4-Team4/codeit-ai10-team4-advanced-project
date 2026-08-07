"""문구 생성 — 후보 3건, 헤드라인+서브."""

from app_core import copy_gen
from app_core.schema import AdBrief, Store


class FakeClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.system: str | None = None

    def complete_json(self, system: str, user: str) -> dict:
        self.system = system
        return self.response


def brief(**kw) -> AdBrief:
    return AdBrief(**{"goal": "copy", "product": "크로플", "price": 4500, **kw})


def three(**kw) -> dict:
    item = {"headline": "겨울 감성 크로플", "sub": "지금 4,500원", **kw}
    return {"candidates": [item, item, item]}


def test_후보를_돌려준다(store: Store) -> None:
    result = copy_gen.generate(brief(), store, client=FakeClient(three()))
    assert len(result) == 3
    assert result[0].headline == "겨울 감성 크로플"


def test_3건을_넘으면_잘라낸다(store: Store) -> None:
    many = {"candidates": [{"headline": f"문구{i}"} for i in range(10)]}
    assert len(copy_gen.generate(brief(), store, client=FakeClient(many))) == 3


def test_헤드라인이_빈_후보는_버린다(store: Store) -> None:
    mixed = {"candidates": [{"headline": ""}, {"headline": "겨울 크로플"}]}
    result = copy_gen.generate(brief(), store, client=FakeClient(mixed))
    assert [c.headline for c in result] == ["겨울 크로플"]


def test_너무_긴_문구는_자른다(store: Store) -> None:
    long = {"candidates": [{"headline": "가" * 100, "sub": "나" * 100}]}
    result = copy_gen.generate(brief(), store, client=FakeClient(long))
    assert len(result[0].headline) == copy_gen.MAX_HEADLINE
    assert len(result[0].sub) == copy_gen.MAX_SUB


def test_서브를_안_원하면_비운다(store: Store) -> None:
    result = copy_gen.generate(brief(with_sub=False), store, client=FakeClient(three()))
    assert result[0].sub == ""


def test_빈_응답이어도_안_터진다(store: Store) -> None:
    assert copy_gen.generate(brief(), store, client=FakeClient({})) == []


def test_가격이_있으면_프롬프트에_넣는다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(brief(price=4500), store, client=client)
    assert client.system is not None and "4,500원" in client.system


def test_가격이_0이면_넣지_말라고_한다(store: Store) -> None:
    """0원은 '가격 없음'이다. 광고에 0원이라고 쓰면 안 된다."""
    client = FakeClient(three())
    copy_gen.generate(brief(price=0), store, client=client)
    assert client.system is not None
    assert "가격을 넣지 마라" in client.system


def test_지어내지_말라고_지시한다(store: Store) -> None:
    """없는 가격·수상 이력을 쓰면 표시광고법 위반이다."""
    client = FakeClient(three())
    copy_gen.generate(brief(), store, client=client)
    assert client.system is not None and "지어내지 마라" in client.system


def test_최근_이력을_프롬프트에_넣는다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(brief(), store, recent=[brief(product="아메리카노")], client=client)
    assert client.system is not None and "아메리카노" in client.system


def test_이력이_없으면_그_부분을_빼고_보낸다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(brief(), store, recent=[], client=client)
    assert client.system is not None and "전에 만든 광고" not in client.system
