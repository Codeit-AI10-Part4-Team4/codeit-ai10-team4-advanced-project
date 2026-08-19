"""문구 품질 지표 — 나온 문구만 보고 재는 순수 함수인지, 채점이 맞는지 확인한다.

계기판 쪽(`ungrounded_claims`)은 **오탐이 안 나는 것**을 특히 본다.
잘못 울리면 결국 아무도 안 보게 되기 때문이다.
"""

from eval.copy_metrics import amounts, price_violations, ungrounded_claims

# ── 금액 뽑기 ────────────────────────────────────────────────


def test_쉼표가_있어도_읽는다() -> None:
    assert amounts("크로플 4,500원") == {4500}


def test_쉼표가_없어도_읽는다() -> None:
    assert amounts("크로플 4500원") == {4500}


def test_만원_천원_단위를_환산한다() -> None:
    assert amounts("1만원") == {10_000}
    assert amounts("5천원") == {5_000}


def test_금액이_없으면_빈_집합() -> None:
    assert amounts("오늘만 특별하게") == set()


def test_숫자만_있고_원이_없으면_금액이_아니다() -> None:
    """`"2개"`·`"1인분"` 을 가격으로 읽으면 오탐이 쏟아진다."""
    assert amounts("2개 주문시 1인분 서비스") == set()


# ── 가격 규칙 ────────────────────────────────────────────────


def test_가격을_빼라고_했는데_넣으면_걸린다() -> None:
    """`show_price=False` 는 사장님이 가격 없이 만들기를 원한 것이다."""
    hits = price_violations("크로플 4,500원", show_price=False, price=0)
    assert len(hits) == 1
    assert "4,500원" in hits[0]


def test_가격을_빼라고_했고_안_넣었으면_통과() -> None:
    assert price_violations("따뜻한 오후의 크로플", show_price=False, price=0) == []


def test_주문서와_같은_금액이면_통과() -> None:
    assert price_violations("크로플 4,500원", show_price=True, price=4500) == []


def test_주문서에_없는_금액을_쓰면_걸린다() -> None:
    """지어낸 가격은 표시광고법에 걸린다."""
    hits = price_violations("크로플 3,900원", show_price=True, price=4500)
    assert len(hits) == 1
    assert "3,900원" in hits[0]


def test_가격을_아예_안_쓴_것은_위반이_아니다() -> None:
    """넣으라고 강제한 적은 없다 — 다른 금액을 쓰는 것이 문제다."""
    assert price_violations("바삭한 크로플", show_price=True, price=4500) == []


# ── 근거 없는 주장 ───────────────────────────────────────────


def test_사장님이_말한_적_없는_주장은_걸린다() -> None:
    hits = ungrounded_claims("국산 재료로 만든 크로플", grounds="크로플 신메뉴 따뜻한")
    assert ("재료", "국산") in hits


def test_사장님이_말했으면_걸리지_않는다() -> None:
    """근거가 있는 말이다. 이걸 걸면 사장님 말을 못 쓰게 된다."""
    assert ungrounded_claims("국산 재료로 만든 크로플", grounds="국산 밀로 만든 크로플") == []


def test_사진에서_읽은_것도_근거로_본다() -> None:
    """아무것도 없는 데서 지어낸 것과는 다르다. 오탐을 안 만드는 쪽을 골랐다."""
    assert ungrounded_claims("수제 크로플", grounds="- 눈에 띄는 점: 수제로 구운 겉면") == []


def test_상투어는_걸지_않는다() -> None:
    """`"맛있는"`·`"좋은"` 까지 걸면 거의 모든 문구가 걸려 신호가 죽는다."""
    assert ungrounded_claims("맛있는 크로플, 좋은 하루", grounds="크로플") == []


def test_갈래를_함께_돌려준다() -> None:
    """무엇을 고쳐야 할지는 갈래를 봐야 안다."""
    hits = ungrounded_claims("최고의 수제 크로플", grounds="크로플")
    assert ("품질·등급", "최고") in hits
    assert ("재료", "수제") in hits


def test_근거_없는_주장이_없으면_빈_목록() -> None:
    assert ungrounded_claims("천천히 머무는 오후, 크로플", grounds="크로플 따뜻한") == []
