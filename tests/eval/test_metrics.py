"""지표 함수 — (예측, 정답)만 받는 순수 함수인지, 채점이 맞는지 확인한다."""

import pytest

from eval.metrics import failures, overall_accuracy, slot_accuracy, slot_hit


def row(**kw) -> dict:
    return {"product": None, "price": None, "situation": "", "tone": "", **kw}


# ── 슬롯 하나 채점 ───────────────────────────────────────────


def test_정확_슬롯은_값이_같아야_맞다() -> None:
    assert slot_hit("product", "크로플", "크로플") is True
    assert slot_hit("product", "크로플", "아메리카노") is False


def test_가격_0과_None은_다르다() -> None:
    """0 은 '가격 없음', None 은 '아직 안 물어봄'. 섞으면 가격을 안 묻고 넘어간다."""
    assert slot_hit("price", 0, None) is False
    assert slot_hit("price", None, 0) is False


def test_자유_슬롯은_값이_달라도_맞다() -> None:
    """ "판매 부진"과 "판매량 늘리기"는 둘 다 맞는 답이다."""
    assert slot_hit("situation", "판매량 늘리기", "판매 부진") is True


def test_자유_슬롯도_비면_틀리다() -> None:
    assert slot_hit("situation", "", "판매 부진") is False


def test_안_뽑혀야_하는데_뽑으면_틀리다() -> None:
    """지어낸 값도 잡아야 한다."""
    assert slot_hit("tone", "따뜻한", "") is False


def test_둘_다_비면_맞다() -> None:
    assert slot_hit("tone", "", "") is True


# ── 집계 ────────────────────────────────────────────────────


def test_다_맞으면_100퍼센트() -> None:
    r = row(product="크로플", price=4500, situation="신메뉴")
    assert slot_accuracy([r], [r]) == {
        "product": 1.0,
        "price": 1.0,
        "situation": 1.0,
        "tone": 1.0,
    }
    assert overall_accuracy([r], [r]) == 1.0


def test_한_슬롯만_틀리면_그_슬롯만_깎인다() -> None:
    pred = row(product="크로플", price=4500)
    gold = row(product="크로플", price=6000)
    scores = slot_accuracy([pred], [gold])
    assert scores["product"] == 1.0
    assert scores["price"] == 0.0


def test_한_슬롯이라도_틀리면_전체_일치는_0() -> None:
    assert overall_accuracy([row(product="크로플")], [row(product="아메리카노")]) == 0.0


def test_여러_행의_평균을_낸다() -> None:
    preds = [row(product="크로플"), row(product="라떼")]
    golds = [row(product="크로플"), row(product="아메리카노")]
    assert slot_accuracy(preds, golds)["product"] == 0.5


def test_빈_데이터셋은_0점() -> None:
    assert overall_accuracy([], []) == 0.0
    assert slot_accuracy([], [])["product"] == 0.0


def test_예측과_정답_개수가_다르면_거부한다() -> None:
    with pytest.raises(ValueError, match="개수"):
        slot_accuracy([row()], [])


# ── 틀린 것 추리기 ───────────────────────────────────────────


def test_틀린_것만_추린다() -> None:
    """점수만 보면 무엇이 왜 틀렸는지 알 수 없다."""
    preds = [row(product="크로플"), row(product="라떼")]
    golds = [row(product="크로플"), row(product="아메리카노")]
    wrong = failures(preds, golds)
    assert len(wrong) == 1
    idx, slots = wrong[0]
    assert idx == 1
    assert slots["product"] == ("라떼", "아메리카노")


def test_다_맞으면_추릴_것이_없다() -> None:
    r = row(product="크로플")
    assert failures([r], [r]) == []
