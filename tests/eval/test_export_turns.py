"""턴 로그 → 골든셋 후보 변환."""

from eval.export_turns import to_rows


def entry(utterance: str, after: dict, before: dict | None = None, **kw) -> dict:
    empty = {"product": None, "price": None, "situation": "", "tone": "", "extra": ""}
    return {
        "utterance": utterance,
        "before": {**empty, **(before or {})},
        "after": {**empty, **after},
        "asked": kw.get("asked", "product"),
        "industry": kw.get("industry", "카페·디저트"),
    }


def test_뽑힌_값이_후보_정답이_된다() -> None:
    rows = to_rows([entry("크로플이요", {"product": "크로플"})])
    assert rows[0]["utterance"] == "크로플이요"
    assert rows[0]["product"] == "크로플"


def test_안_뽑힌_슬롯은_빈칸() -> None:
    """빈칸의 뜻은 골든셋과 같다 — 그 슬롯은 안 뽑혀야 한다."""
    rows = to_rows([entry("크로플이요", {"product": "크로플"})])
    assert rows[0]["price"] == ""
    assert rows[0]["tone"] == ""


def test_가격_0은_빈칸이_아니다() -> None:
    """0 은 '가격 없음'이라는 값이다. 미언급(빈칸)과 구분해야 한다."""
    rows = to_rows([entry("가격은 빼주세요", {"price": 0})])
    assert rows[0]["price"] == "0"


def test_빈_주문서에서_시작하면_empty() -> None:
    rows = to_rows([entry("크로플이요", {"product": "크로플"})])
    assert rows[0]["start"] == "empty"


def test_이미_차_있었으면_filled() -> None:
    """정정 케이스는 평가 방식이 달라서 구분해둬야 한다."""
    rows = to_rows(
        [entry("아니 6000원이요", {"price": 6000}, before={"product": "크로플", "price": 4500})]
    )
    assert rows[0]["start"] == "filled"


def test_같은_발화는_한_번만_남긴다() -> None:
    """ "4500원" 같은 말은 여러 세션에서 반복된다."""
    rows = to_rows([entry("4500원", {"price": 4500}), entry("4500원", {"price": 4500})])
    assert len(rows) == 1


def test_출처는_real() -> None:
    """실제 대화에서 나온 발화라는 표시."""
    assert to_rows([entry("크로플이요", {"product": "크로플"})])[0]["source"] == "real"


def test_검수하라는_표시가_붙는다() -> None:
    """LLM 이 뽑은 값을 그대로 정답으로 쓰면 자기 채점이 된다."""
    note = to_rows([entry("크로플이요", {"product": "크로플"}, asked="price")])[0]["note"]
    assert "검수" in note
    assert "price" in note


def test_빈_발화는_건너뛴다() -> None:
    assert to_rows([entry("   ", {})]) == []


def test_로그가_비면_빈_목록() -> None:
    assert to_rows([]) == []
