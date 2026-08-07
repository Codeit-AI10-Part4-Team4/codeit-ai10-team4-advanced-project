"""챗봇 — LLM 응답에서 검증을 통과한 값만 주문서에 들어가는지 확인한다.

FakeClient 로 응답을 미리 정해둔다 — 실 API 호출은 비용·비결정성 때문에 금지.
"""

from app_core import chat
from app_core.schema import AdBriefDraft, Store


class FakeClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.system: str | None = None

    def complete_json(self, system: str, user: str) -> dict:
        self.system = system
        return self.response


def draft(**kw) -> AdBriefDraft:
    return AdBriefDraft(**{"goal": "image", **kw})


def test_뽑아낸_값이_주문서에_들어간다(store: Store) -> None:
    turn = chat.respond(
        draft(),
        "크로플 4500원이야",
        store,
        FakeClient({"message": "좋아요", "extracted": {"product": "크로플", "price": 4500}}),
    )
    assert turn.draft.product == "크로플" and turn.draft.price == 4500
    assert turn.draft.missing() == []


def test_선택지를_함께_돌려준다(store: Store) -> None:
    turn = chat.respond(
        draft(),
        "사진 만들어줘",
        store,
        FakeClient({"message": "뭘 홍보할까요?", "options": ["신메뉴", "할인"]}),
    )
    assert turn.options == ["신메뉴", "할인"]


def test_느낌을_말하면_tone에_들어간다(store: Store) -> None:
    turn = chat.respond(
        draft(product="크로플", price=4500),
        "매운 감칠맛을 부각해줘",
        store,
        FakeClient({"extracted": {"tone": "매운 감칠맛 강조"}}),
    )
    assert turn.draft.tone == "매운 감칠맛 강조"


def test_다_찼으면_선택지를_지운다(store: Store) -> None:
    """LLM 이 지시를 어기고 또 물어봐도 대화가 맴돌지 않게 한다."""
    turn = chat.respond(
        draft(product="크로플"),
        "4500원",
        store,
        FakeClient({"message": "느낌은요?", "options": ["따뜻하게"], "extracted": {"price": 4500}}),
    )
    assert turn.draft.missing() == []
    assert turn.options == []


def test_필수가_남으면_마무리하라고_안_한다(store: Store) -> None:
    client = FakeClient({})
    chat.respond(draft(product="크로플"), "안녕", store, client)
    assert client.system is not None
    assert "하나만" in client.system


def test_다_차면_마무리하라고_지시한다(store: Store) -> None:
    """이게 없으면 선택 항목을 채우려고 같은 질문을 되풀이한다."""
    client = FakeClient({})
    chat.respond(draft(product="크로플", price=4500), "안녕", store, client)
    assert client.system is not None
    assert "더 묻지 말고 마무리해라" in client.system


def test_가격을_안_말했으면_0을_넣지_말라고_지시한다(store: Store) -> None:
    """0 은 '가격 빼달라'는 뜻이다. LLM 이 모르겠다는 뜻으로 0 을 넣으면
    가격을 아예 안 물어보고 넘어간다."""
    client = FakeClient({})
    chat.respond(draft(), "안녕", store, client)
    assert client.system is not None
    assert "0 도 넣지 마라" in client.system


def test_가격_0은_사장님이_말했을_때만_받는다(store: Store) -> None:
    """규칙은 프롬프트로 지시하고, 실제로 0 이 오면 그대로 받는다."""
    turn = chat.respond(
        draft(product="크로플"),
        "가격은 안 넣을래요",
        store,
        FakeClient({"extracted": {"price": 0}}),
    )
    assert turn.draft.price == 0
    assert turn.draft.missing() == []


def test_이전_값을_유지한_채_합친다(store: Store) -> None:
    turn = chat.respond(
        draft(product="크로플"),
        "4500원",
        store,
        FakeClient({"extracted": {"price": 4500}}),
    )
    assert turn.draft.product == "크로플" and turn.draft.price == 4500


def test_형식이_틀린_슬롯만_버린다(store: Store) -> None:
    """가격에 글자가 와도 상품명은 살아남아야 한다."""
    turn = chat.respond(
        draft(),
        "크로플인데 가격은 몰라",
        store,
        FakeClient({"extracted": {"product": "크로플", "price": "사천오백원"}}),
    )
    assert turn.draft.product == "크로플"
    assert turn.draft.price is None


def test_음수_가격은_버린다(store: Store) -> None:
    turn = chat.respond(draft(), "?", store, FakeClient({"extracted": {"price": -100}}))
    assert turn.draft.price is None


def test_빈_응답이어도_안_터진다(store: Store) -> None:
    """LLM 이 형식을 어겨도 대화가 멈추면 안 된다."""
    turn = chat.respond(draft(), "음...", store, FakeClient({}))
    assert turn.message
    assert turn.options == []


def test_선택지가_목록이_아니면_무시한다(store: Store) -> None:
    turn = chat.respond(draft(), "?", store, FakeClient({"options": "신메뉴"}))
    assert turn.options == []


def test_프롬프트에_가게_정보가_들어간다(store: Store) -> None:
    """업종·상호를 모르면 맞는 질문을 못 한다."""
    client = FakeClient({})
    chat.respond(draft(), "안녕", store, client)
    assert client.system is not None
    assert "연남 크로플" in client.system
    assert "카페" in client.system


def test_프롬프트에_안_찬_항목이_들어간다(store: Store) -> None:
    client = FakeClient({})
    chat.respond(draft(product="크로플"), "안녕", store, client)
    assert client.system is not None
    assert "가격" in client.system
