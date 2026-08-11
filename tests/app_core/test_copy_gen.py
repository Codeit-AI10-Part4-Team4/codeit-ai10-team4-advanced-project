"""문구 생성 — 후보 3건, 헤드라인+서브."""

from app_core import copy_gen
from app_core.schema import AdBrief, CopyCandidate, Feedback, Store


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


def test_사장님이_한_말_원문을_넣는다(store: Store) -> None:
    """슬롯으로 요약하면서 깎인 뉘앙스를 원문에서 살린다."""
    said = "단골분들이 매콤한 걸 좋아하셔서 이번에 낸 거예요"
    client = FakeClient(three())
    copy_gen.generate(brief(transcript=[said]), store, client=client)
    assert client.system is not None and said in client.system


def test_말이_없으면_그_부분을_빼고_보낸다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(brief(transcript=[]), store, client=client)
    assert client.system is not None and "원문" not in client.system


# ── 다시 만들기 ──────────────────────────────────────────────


def revised(**kw) -> AdBrief:
    fb = kw.pop("feedback", Feedback(source="typed", notes=["좀 더 밝게"]))
    prev = kw.pop("prev", [CopyCandidate(headline="겨울 감성 크로플", sub="지금 4,500원")])
    return brief(**kw).revised(fb, prev)


def test_처음_만들_때는_재생성_안내가_없다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(brief(), store, client=client)
    assert client.system is not None and "다시 만드는 중" not in client.system


def test_고쳐달라는_말을_프롬프트에_넣는다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(revised(), store, client=client)
    assert client.system is not None
    assert "다시 만드는 중" in client.system
    assert "좀 더 밝게" in client.system


def test_직전_문구를_보여주고_다르게_만들라고_한다(store: Store) -> None:
    """안 보여주면 같은 걸 또 내놓는다."""
    client = FakeClient(three())
    copy_gen.generate(revised(), store, client=client)
    assert client.system is not None
    assert "겨울 감성 크로플" in client.system
    assert "다르게" in client.system


def test_패널_평가는_저항_요인까지_넣는다(store: Store) -> None:
    client = FakeClient(three())
    fb = Feedback(source="panel", notes=["묶음가로 제시"], resistance=["가격"])
    copy_gen.generate(revised(feedback=fb), store, client=client)
    assert client.system is not None
    assert "AI 손님 패널" in client.system
    assert "가격" in client.system


def test_선택지로_고쳐도_같은_자리에_들어간다(store: Store) -> None:
    client = FakeClient(three())
    fb = Feedback(source="option", notes=["더 짧게"])
    copy_gen.generate(revised(feedback=fb), store, client=client)
    assert client.system is not None and "더 짧게" in client.system


def test_직전_문구가_없어도_안_터진다(store: Store) -> None:
    client = FakeClient(three())
    assert copy_gen.generate(revised(prev=[]), store, client=client)


def test_재생성해도_지어내지_말라는_지시는_남는다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(revised(), store, client=client)
    assert client.system is not None and "지어내지 마라" in client.system
