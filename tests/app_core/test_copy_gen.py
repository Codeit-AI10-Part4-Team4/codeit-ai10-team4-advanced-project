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


def test_너무_긴_문구는_버린다(store: Store) -> None:
    """자르면 "…특가 이벤" 처럼 중간에서 끊긴 문구가 사장님 화면에 뜬다."""
    long = {"candidates": [{"headline": "가" * 100, "sub": "나" * 100}]}
    assert copy_gen.generate(brief(), store, client=FakeClient(long)) == []


def test_서브만_길어도_버린다(store: Store) -> None:
    long_sub = {"candidates": [{"headline": "겨울 크로플", "sub": "나" * 100}]}
    assert copy_gen.generate(brief(), store, client=FakeClient(long_sub)) == []


def test_긴_후보_하나가_나머지를_죽이지_않는다(store: Store) -> None:
    """후보는 하나씩 따로 판단한다."""
    mixed = {"candidates": [{"headline": "가" * 100}, {"headline": "겨울 크로플"}]}
    result = copy_gen.generate(brief(), store, client=FakeClient(mixed))
    assert [c.headline for c in result] == ["겨울 크로플"]


def test_길이만_맞으면_그대로_쓴다(store: Store) -> None:
    exact = {"candidates": [{"headline": "가" * copy_gen.MAX_HEADLINE}]}
    result = copy_gen.generate(brief(), store, client=FakeClient(exact))
    assert len(result) == 1


def test_서브를_안_만들_때는_서브_길이를_보지_않는다(store: Store) -> None:
    """with_sub=False 면 sub 를 비우므로 LLM 이 길게 줬어도 상관없다."""
    long_sub = {"candidates": [{"headline": "겨울 크로플", "sub": "나" * 100}]}
    result = copy_gen.generate(brief(with_sub=False), store, client=FakeClient(long_sub))
    assert [c.headline for c in result] == ["겨울 크로플"]


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


# ── 상품 사진 ────────────────────────────────────────────────


def test_사진에서_읽은_것을_프롬프트에_넣는다(store: Store) -> None:
    note = "- 찍힌 것: 크로플\n- 사진의 분위기: 따뜻하고 아늑한"
    client = FakeClient(three())
    copy_gen.generate(brief(photo_id=1, photo_note=note), store, client=client)
    assert client.system is not None and "따뜻하고 아늑한" in client.system


def test_사진_메모는_사장님_말과_구분해서_넣는다(store: Store) -> None:
    """섞어 놓으면 사장님이 하지도 않은 말이 문구의 근거가 된다."""
    client = FakeClient(three())
    copy_gen.generate(brief(photo_note="- 찍힌 것: 크로플"), store, client=client)
    assert client.system is not None and "사장님이 한 말이 아니다" in client.system


def test_사진이_없으면_그_부분을_빼고_보낸다(store: Store) -> None:
    client = FakeClient(three())
    copy_gen.generate(brief(), store, client=client)
    assert client.system is not None and "사진에서 읽은 것" not in client.system


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


# ── 수량 오인 거르기 ────────────────────────────────────────
#
# 금액 자체는 맞는데 "무엇의 금액인가" 가 틀린 경우다. 가격 검사로는 안 잡힌다.


def event_brief() -> AdBrief:
    """한 캔 2,000원짜리 카스에 2+1 행사를 얹은 주문."""
    return AdBrief(
        goal="copy",
        product="카스",
        price=2000,
        situation="2 + 1 이벤트",
        transcript=["2000원", "2 + 1 이벤트 홍보하려고"],
    )


def test_한_개_값을_행사에_붙인_후보는_버린다(store: Store) -> None:
    """2,000원은 한 캔 값이다. "2,000원에 2+1" 은 세 캔을 2,000원에 준다는 뜻이 된다."""
    raw = {
        "candidates": [
            {"headline": "카스 한 잔 2,000원", "sub": "2 + 1 이벤트 진행 중"},
            {"headline": "카스 2+1", "sub": "2,000원에 2 + 1으로 만나요"},
        ]
    }
    got = copy_gen.generate(event_brief(), store, client=FakeClient(raw))
    assert [c.headline for c in got] == ["카스 한 잔 2,000원"]


def test_사장님이_말한_적_없는_개수는_버린다(store: Store) -> None:
    """2+1 은 두 잔 값에 세 잔이다 — "한 잔 값에 세 잔" 은 사장님이 한 말이 아니다."""
    raw = {"candidates": [{"headline": "카스 이벤트", "sub": "한 잔 값에 세 잔 즐기세요"}]}
    assert copy_gen.generate(event_brief(), store, client=FakeClient(raw)) == []


def test_한_개_값에_개수를_붙이면_버린다(store: Store) -> None:
    raw = {"candidates": [{"headline": "크로플 두 개 4,500원"}]}
    assert copy_gen.generate(brief(), store, client=FakeClient(raw)) == []


def test_개수를_말하지_않은_문구는_통과한다(store: Store) -> None:
    """거르개가 멀쩡한 문구까지 잡으면 후보가 남지 않는다."""
    raw = {"candidates": [{"headline": "겨울 크로플", "sub": "지금 4,500원"}]}
    assert len(copy_gen.generate(brief(), store, client=FakeClient(raw))) == 1


def test_사장님이_바로잡은_금액은_쓸_수_있다(store: Store) -> None:
    """다시 만들기로 하신 정정도 사장님 말이라 근거가 된다."""
    fixed = event_brief().revised(
        Feedback(source="typed", notes=["한 캔에 2000원이니까 2+1 행사면 카스 3캔에 4000원이다"]),
        [],
    )
    raw = {"candidates": [{"headline": "카스 2+1 이벤트", "sub": "한 캔에 2,000원, 3캔에 4,000원"}]}
    got = copy_gen.generate(fixed, store, client=FakeClient(raw))
    assert [c.sub for c in got] == ["한 캔에 2,000원, 3캔에 4,000원"]


def test_금액_옆에_행사표기를_붙이면_버린다(store: Store) -> None:
    """2,000원은 한 캔 값이다 — "2,000원에 2+1" 은 세 캔을 2,000원에 준다는 뜻이 된다.

    개수가 금액에 더 가까우면("2+1 행사, 한 캔 2,000원") 금액은 그 한 캔에 붙은
    것이라 멀쩡하다. 붙은 순서가 뜻을 바꾼다.
    """
    raw = {
        "candidates": [
            {"headline": "카스 특가", "sub": "2,000원에 2+1으로 만나요!"},
            {"headline": "카스 행사", "sub": "2+1 행사 · 한 캔 2,000원!"},
        ]
    }
    got = copy_gen.generate(event_brief(), store, client=FakeClient(raw))
    assert [c.sub for c in got] == ["2+1 행사 · 한 캔 2,000원!"]


def test_행사를_풀어_쓴_개수는_버린다(store: Store) -> None:
    """실제로 화면에 떴던 문구다. 2+1 은 **두 캔 값에 세 캔**이지 한 캔 값에 두 캔이 아니다."""
    raw = {
        "candidates": [
            {"headline": "청량한 카스, 2+1!", "sub": "한 캔에 2000원으로 두 캔의 기쁨을!"}
        ]
    }
    assert copy_gen.generate(event_brief(), store, client=FakeClient(raw)) == []


def test_행사_표기를_바꿔_쓰면_버린다(store: Store) -> None:
    """사장님은 2+1 이라고 하셨다. 1+1 은 다른 조건이다."""
    raw = {"candidates": [{"headline": "카스 1+1 행사!", "sub": "시원하게 즐기세요"}]}
    assert copy_gen.generate(event_brief(), store, client=FakeClient(raw)) == []


def test_사장님이_쓴_행사_표기는_그대로_통과한다(store: Store) -> None:
    raw = {"candidates": [{"headline": "카스 2+1 행사!", "sub": "청량함을 만끽하세요"}]}
    assert len(copy_gen.generate(event_brief(), store, client=FakeClient(raw))) == 1
