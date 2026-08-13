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


def test_더_물을_게_없으면_선택지를_지운다(store: Store) -> None:
    """LLM 이 지시를 어기고 또 물어봐도 대화가 맴돌지 않게 한다."""
    done = draft(product="크로플", price=4500, situation="신메뉴", tone="따뜻한")
    turn = chat.respond(
        done, "네", store, FakeClient({"message": "더 없나요?", "options": ["있어요"]})
    )
    assert turn.draft.next_slot() is None
    assert turn.options == []


def test_더_물을_게_없으면_마무리_인사는_코드가_쓴다(store: Store) -> None:
    """LLM 이 또 질문을 만들어도 화면에는 안 나가야 한다.

    실제로 그랬다 — 프롬프트 JSON 틀의 예시("가격"·"원하는 느낌")를 베껴서
    다 채워진 뒤에도 그 둘을 번갈아 물었다.
    """
    done = draft(product="크로플", price=4500, situation="신메뉴", tone="따뜻한")
    turn = chat.respond(done, "네", store, FakeClient({"message": "가격은 얼마인가요?"}))
    assert turn.message == chat.DONE_MESSAGE


def test_마지막_슬롯이_이번_턴에_차도_마무리한다(store: Store) -> None:
    """이번 말로 마지막 칸이 차는 순간이 실제로 터진 지점이다."""
    almost = draft(product="크로플", price=4500, situation="신메뉴")
    turn = chat.respond(
        almost,
        "매운 감칠맛 강조",
        store,
        FakeClient({"extracted": {"tone": "매운 감칠맛 강조"}, "message": "가격은 얼마인가요?"}),
    )
    assert turn.message == chat.DONE_MESSAGE
    assert turn.options == []


def test_아직_물을_게_남으면_LLM_말을_그대로_쓴다(store: Store) -> None:
    turn = chat.respond(
        draft(product="크로플"), "네", store, FakeClient({"message": "가격은 얼마인가요?"})
    )
    assert turn.message == "가격은 얼마인가요?"


def test_이미지_광고의_가격은_협박하지_않고_묻는다(store: Store) -> None:
    """이미지 광고에서 가격은 선택이다. 상수만 보면 "없으면 못 만든다"고 한다."""
    client = FakeClient({})
    chat.respond(draft(goal="image", product="크로플"), "안녕", store, client)
    assert client.system is not None
    assert "가격" in client.system
    assert "없으면 광고를 못 만든다" not in client.system
    assert "빠져나갈 길" in client.system  # ASK_HELPFUL 쪽 지시


def test_필수가_남으면_그것부터_물으라고_지시한다(store: Store) -> None:
    # 가격이 필수인 건 문구 광고다. 이미지 광고는 선택이다 (schema.required).
    client = FakeClient({})
    chat.respond(draft(goal="copy", product="크로플"), "안녕", store, client)
    assert client.system is not None
    assert "가격" in client.system
    assert "없으면 광고를 못 만든다" in client.system


def test_필수가_차면_느낌을_물으라고_지시한다(store: Store) -> None:
    """필수만 채우고 끝내면 사장님 의도를 못 담는다."""
    client = FakeClient({})
    chat.respond(draft(product="크로플", price=4500, situation="신메뉴"), "네", store, client)
    assert client.system is not None
    assert "원하는 느낌" in client.system
    assert "부담 주지 마라" in client.system


def test_다_물었으면_마무리하라고_지시한다(store: Store) -> None:
    client = FakeClient({})
    full = draft(product="크로플", price=4500, situation="신메뉴", tone="따뜻한")
    chat.respond(full, "네", store, client)
    assert client.system is not None
    assert "더 묻지 마라" in client.system


def test_한_번_물어본_것은_다시_묻지_않는다(store: Store) -> None:
    """사장님이 답을 피해도 같은 질문을 되풀이하면 안 된다."""
    d = draft(product="크로플", price=4500)

    first = chat.respond(d, "네", store, FakeClient({})).draft
    assert first.asked == ["situation"]  # 상황을 물었다

    # 답을 안 했는데도 다음 턴엔 상황이 아니라 느낌을 묻는다
    client = FakeClient({})
    chat.respond(first, "글쎄요", store, client)
    assert client.system is not None
    assert "원하는 느낌" in client.system


def test_결국_물어볼_게_바닥난다(store: Store) -> None:
    """무한 반복하지 않는다."""
    d = draft(product="크로플", price=4500)
    for _ in range(5):
        d = chat.respond(d, "글쎄요", store, FakeClient({})).draft
    assert d.next_slot() is None


def test_가격을_안_말했으면_0을_넣지_말라고_지시한다(store: Store) -> None:
    """0 은 '가격 빼달라'는 뜻이다. LLM 이 모르겠다는 뜻으로 0 을 넣으면
    가격을 아예 안 물어보고 넘어간다."""
    client = FakeClient({})
    chat.respond(draft(), "안녕", store, client)
    assert client.system is not None
    assert "0 도 넣지 마라" in client.system


def test_사장님이_한_말이_기록된다(store: Store) -> None:
    turn = chat.respond(draft(), "크로플 홍보하고 싶어", store, FakeClient({}))
    assert turn.draft.transcript == ["크로플 홍보하고 싶어"]


def test_아무것도_못_뽑아내도_말은_남는다(store: Store) -> None:
    """슬롯에 안 담기는 뉘앙스가 여기서 살아남는다."""
    said = "단골분들이 매콤한 걸 좋아하셔서 이번에 낸 거예요"
    turn = chat.respond(draft(), said, store, FakeClient({}))
    assert turn.draft.transcript == [said]


def test_말이_쌓인다(store: Store) -> None:
    d = draft()
    for said in ["크로플이요", "4500원", "따뜻하게"]:
        d = chat.respond(d, said, store, FakeClient({})).draft
    assert d.transcript == ["크로플이요", "4500원", "따뜻하게"]


def test_빈_입력은_기록하지_않는다(store: Store) -> None:
    turn = chat.respond(draft(), "   ", store, FakeClient({}))
    assert turn.draft.transcript == []


def test_프롬프트에_지금까지_한_말이_들어간다(store: Store) -> None:
    client = FakeClient({})
    chat.respond(draft(transcript=["단골분들이 매콤한 걸 좋아해요"]), "네", store, client)
    assert client.system is not None
    assert "단골분들이 매콤한 걸 좋아해요" in client.system


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
