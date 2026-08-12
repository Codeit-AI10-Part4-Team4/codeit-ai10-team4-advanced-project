"""주문서 스키마 — 틀린 값이 여기서 걸리는지 검증한다."""

import pytest
from pydantic import ValidationError

from app_core.schema import AdBrief, AdBriefDraft, CopyCandidate, Feedback, StoreInput

CAFE = "cafe"


def store_input(**kw) -> StoreInput:
    return StoreInput(**{"industry": CAFE, "name": "연남 크로플", **kw})


def brief(**kw) -> AdBrief:
    return AdBrief(**{"goal": "image", "product": "크로플", "price": 4500, **kw})


# ── 가게 등록 ────────────────────────────────────────────────


def test_정상_등록() -> None:
    s = store_input(address="서울시 마포구 연남동 1-2", phone="02-000-0000")
    assert s.industry == CAFE and s.name == "연남 크로플"


def test_모르는_업종은_거부한다() -> None:
    """LLM 이나 폼에서 목록 밖 값이 오면 여기서 막힌다."""
    with pytest.raises(ValidationError, match="모르는 업종"):
        store_input(industry="우주정거장")


def test_서울_밖_주소는_거부한다() -> None:
    """상권 데이터가 서울 기준이라, 나중에 조회 단계에서 실패하기 전에 막는다."""
    with pytest.raises(ValidationError, match="서울"):
        store_input(address="부산광역시 해운대구")


def test_주소가_없으면_서울로_풀백한다() -> None:
    assert store_input().address == "서울"


def test_상호는_필수다() -> None:
    with pytest.raises(ValidationError):
        store_input(name="")


def test_모르는_필드는_거부한다() -> None:
    """오타로 만든 필드가 조용히 무시되면 안 된다."""
    with pytest.raises(ValidationError):
        store_input(addres="서울시 마포구")


def test_목록에_있으면_그_이름을_쓴다() -> None:
    assert store_input(industry="cafe").industry_label == "카페·디저트"


def test_기타는_직접_적은_업종명을_쓴다() -> None:
    s = store_input(industry="other", industry_note="드라이플라워 공방")
    assert s.industry_label == "드라이플라워 공방"


def test_기타인데_안_적으면_거부한다() -> None:
    """빈칸으로 넘기면 LLM 이 무슨 가게인지 모른 채 문구를 쓰게 된다."""
    with pytest.raises(ValidationError, match="직접 적어"):
        store_input(industry="other")


def test_기타인데_공백만_적어도_거부한다() -> None:
    with pytest.raises(ValidationError, match="직접 적어"):
        store_input(industry="other", industry_note="   ")


# ── 주문서 ──────────────────────────────────────────────────


def test_필수가_다_차면_생성_가능하다() -> None:
    assert brief().product == "크로플"


def test_목적은_두_가지뿐이다() -> None:
    with pytest.raises(ValidationError):
        brief(goal="video")


def test_상품명이_비면_거부한다() -> None:
    with pytest.raises(ValidationError):
        brief(product="")


def test_음수_가격은_거부한다() -> None:
    with pytest.raises(ValidationError):
        brief(price=-100)


def test_가격이_0이면_광고에_안_넣는다() -> None:
    """0원은 '가격 없음'이라는 뜻이다. 0원이라고 쓰면 안 된다."""
    assert brief(price=0).show_price is False


def test_가격이_있으면_광고에_넣는다() -> None:
    assert brief(price=4500).show_price is True


def test_가격을_항목_목록으로_꺼낼_수_있다() -> None:
    """받는 쪽이 [{"name","price"}] 를 기대한다."""
    assert brief(product="크로플", price=4500).items == [{"name": "크로플", "price": "4,500원"}]


def test_가격이_0이면_항목_목록이_빈다() -> None:
    """0 원은 '가격 없음'이므로 0원짜리 항목을 만들면 안 된다."""
    assert brief(price=0).items == []


# ── 사진 ────────────────────────────────────────────────────


def test_사진은_없어도_된다() -> None:
    """None 이면 사진 없이 배경만 만든다."""
    assert brief().photo_id is None


def test_사진_번호를_담는다() -> None:
    """이미지는 JSON 에 못 실어서 보관함 번호만 싣는다."""
    assert brief(photo_id=7).photo_id == 7


def test_용도가_다른_사진은_칸이_다르다() -> None:
    """한 칸에 몰면 살리라는 건지 흉내내라는 건지 받는 쪽이 알 수 없다."""
    b = brief(photo_id=7, ref_id=8, sketch_id=9)
    assert (b.photo_id, b.ref_id, b.sketch_id) == (7, 8, 9)


def test_레퍼런스만_넣을_수도_있다() -> None:
    """ "제품 사진은 없고 이런 느낌으로만 만들어줘" 가 성립한다."""
    b = brief(ref_id=8)
    assert b.ref_id == 8 and b.photo_id is None and b.sketch_id is None


def test_레퍼런스_스케치도_번호는_1부터다() -> None:
    for field in ("ref_id", "sketch_id"):
        with pytest.raises(ValidationError):
            brief(**{field: 0})


def test_사진_번호는_1부터다() -> None:
    """0 이나 음수는 보관함에 없는 번호다."""
    with pytest.raises(ValidationError):
        brief(photo_id=0)


def test_승격해도_사진_번호가_따라간다() -> None:
    d = AdBriefDraft(goal="image", product="크로플", price=4500, photo_id=7)
    assert d.to_brief().photo_id == 7


def test_승격해도_레퍼런스와_스케치가_따라간다() -> None:
    d = AdBriefDraft(goal="image", product="크로플", price=4500, ref_id=8, sketch_id=9)
    b = d.to_brief()
    assert (b.ref_id, b.sketch_id) == (8, 9)


def test_다시_만들어도_사진은_그대로다() -> None:
    """사진을 바꾸려면 다시 올려야 한다. 재생성이 조건을 건드리지 않는다."""
    revised = brief(photo_id=7).revised(Feedback(source="option", notes=["더 짧게"]), [])
    assert revised.photo_id == 7


def test_사진에서_읽은_메모는_별도_자리에_담긴다() -> None:
    """tone 에 섞으면 사장님이 말한 적 없는 값이 주문서에 조용히 들어간다."""
    b = brief(photo_note="- 사진의 분위기: 따뜻하고 아늑한")
    assert b.photo_note and b.tone == ""


def test_승격해도_사진_메모가_따라간다() -> None:
    d = AdBriefDraft(goal="copy", product="크로플", price=4500, photo_note="- 찍힌 것: 크로플")
    assert d.to_brief().photo_note == "- 찍힌 것: 크로플"


# ── 대화 초안 ────────────────────────────────────────────────


def test_빈_초안은_필수가_전부_비어있다() -> None:
    assert AdBriefDraft().missing() == ["product", "price"]


def test_goal은_필수_슬롯이_아니다() -> None:
    """goal 은 고정 버튼으로 정해지므로 대화로 묻지 않는다."""
    assert "goal" not in AdBriefDraft().missing()


def test_한_슬롯만_차도_missing에서_빠진다() -> None:
    assert AdBriefDraft(product="크로플").missing() == ["price"]


def test_가격_0도_채운_것으로_친다() -> None:
    """0 은 '가격 없음'이고, None 은 '아직 안 물어봤다'다 — 섞으면 안 된다."""
    assert AdBriefDraft(product="크로플", price=0).missing() == []


def test_이번_턴에_안_나온_슬롯은_이전_값을_유지한다() -> None:
    draft = AdBriefDraft(product="크로플").merge(AdBriefDraft(price=4500))
    assert draft.product == "크로플" and draft.price == 4500


def test_새_턴이_같은_슬롯을_다시_말하면_덮어쓴다() -> None:
    draft = AdBriefDraft(product="크로플").merge(AdBriefDraft(product="아메리카노"))
    assert draft.product == "아메리카노"


def test_빈_값으로는_기존_값을_지우지_않는다() -> None:
    draft = AdBriefDraft(product="크로플").merge(AdBriefDraft(product=""))
    assert draft.product == "크로플"


def test_다_차면_주문서로_승격한다() -> None:
    draft = AdBriefDraft(goal="image", product="크로플", price=4500)
    assert draft.to_brief().product == "크로플"


def test_안_찼는데_승격하려면_거부한다() -> None:
    with pytest.raises(ValueError, match="아직 안 찬"):
        AdBriefDraft(goal="image", product="크로플").to_brief()


# ── 원문 보관 ────────────────────────────────────────────────


def test_말을_덧붙이면_쌓인다() -> None:
    d = AdBriefDraft().with_utterance("크로플이요").with_utterance("4500원")
    assert d.transcript == ["크로플이요", "4500원"]


def test_빈_말은_안_쌓는다() -> None:
    assert AdBriefDraft().with_utterance("   ").transcript == []


def test_병합해도_말은_안_지워진다() -> None:
    """슬롯은 덮어써도 되지만 말은 쌓이는 것이지 바뀌는 게 아니다."""
    d = AdBriefDraft().with_utterance("크로플이요").merge(AdBriefDraft(product="크로플"))
    assert d.transcript == ["크로플이요"]


def test_승격해도_말이_따라간다() -> None:
    d = AdBriefDraft(goal="image", product="크로플", price=4500).with_utterance("매콤하게요")
    assert d.to_brief().transcript == ["매콤하게요"]


def test_원문을_한_덩어리로_꺼낼_수_있다() -> None:
    b = brief(transcript=["크로플이요", "4500원"])
    assert b.raw_utterance == "크로플이요\n4500원"


# ── 다시 만들기 ──────────────────────────────────────────────


def test_처음_만들_때는_재생성이_아니다() -> None:
    assert brief().is_revision is False
    assert brief().prev_copies == []


def test_피드백을_얹으면_재생성이_된다() -> None:
    revised = brief().revised(
        Feedback(source="typed", notes=["좀 더 밝게"]),
        [CopyCandidate(headline="겨울 크로플")],
    )
    assert revised.is_revision is True
    assert revised.feedback is not None and revised.feedback.notes == ["좀 더 밝게"]
    assert revised.prev_copies == [CopyCandidate(headline="겨울 크로플")]


def test_재생성해도_조건은_그대로다() -> None:
    """조건까지 바꾸면 사장님이 말한 적 없는 값이 조용히 바뀐다."""
    original = brief(product="크로플", price=4500, tone="따뜻한")
    revised = original.revised(Feedback(source="option", notes=["더 짧게"]), [])
    assert (revised.product, revised.price, revised.tone) == ("크로플", 4500, "따뜻한")


@pytest.mark.parametrize("source", ["typed", "option", "panel"])
def test_세_경로_모두_같은_형태로_담긴다(source: str) -> None:
    fb = Feedback(source=source, notes=["고쳐줘"])
    assert brief().revised(fb, []).feedback == fb


def test_패널_평가는_저항_요인도_담는다() -> None:
    fb = Feedback(source="panel", notes=["묶음가로 제시"], resistance=["가격"])
    assert fb.resistance == ["가격"]


def test_이유_없는_재생성은_거부한다() -> None:
    """왜 다시 만드는지 모르면 같은 걸 또 만들게 된다."""
    with pytest.raises(ValidationError):
        Feedback(source="typed", notes=[])


def test_모르는_경로는_거부한다() -> None:
    with pytest.raises(ValidationError):
        Feedback(source="이메일", notes=["고쳐줘"])


# ── 무엇을 물을지 ────────────────────────────────────────────


def test_필수부터_묻는다() -> None:
    assert AdBriefDraft().next_slot() == "product"
    assert AdBriefDraft(product="크로플").next_slot() == "price"


def test_필수가_차면_도움되는_것을_묻는다() -> None:
    """필수만 채우고 끝내면 사장님 의도를 못 담는다."""
    d = AdBriefDraft(product="크로플", price=4500)
    assert d.missing() == []  # 만들 수는 있지만
    assert d.next_slot() == "situation"  # 더 물어볼 게 있다


def test_이미_찬_것은_묻지_않는다() -> None:
    d = AdBriefDraft(product="크로플", price=4500, situation="신메뉴")
    assert d.next_slot() == "tone"


def test_다_차면_물을_게_없다() -> None:
    d = AdBriefDraft(product="크로플", price=4500, situation="신메뉴", tone="따뜻한")
    assert d.next_slot() is None


def test_한_번_물어본_것은_비어도_다시_묻지_않는다() -> None:
    """사장님이 답을 안 해도 넘어가야 한다. 안 그러면 대화가 맴돈다."""
    d = AdBriefDraft(product="크로플", price=4500).mark_asked("situation")
    assert d.situation == ""
    assert d.next_slot() == "tone"


def test_전부_물어봤으면_끝난다() -> None:
    d = AdBriefDraft(product="크로플", price=4500).mark_asked("situation").mark_asked("tone")
    assert d.next_slot() is None


def test_같은_것을_두_번_표시해도_한_번만_쌓인다() -> None:
    d = AdBriefDraft().mark_asked("tone").mark_asked("tone")
    assert d.asked == ["tone"]


def test_병합해도_물어본_기록은_안_지워진다() -> None:
    d = AdBriefDraft().mark_asked("tone").merge(AdBriefDraft(product="크로플"))
    assert d.asked == ["tone"]


# ── 문구 후보 ────────────────────────────────────────────────


def test_헤드라인이_비면_거부한다() -> None:
    with pytest.raises(ValidationError):
        CopyCandidate(headline="")


def test_서브는_없어도_된다() -> None:
    assert CopyCandidate(headline="겨울 감성 크로플").sub == ""
