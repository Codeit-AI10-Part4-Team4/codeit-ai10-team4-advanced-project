"""주문서 스키마 — 틀린 값이 여기서 걸리는지 검증한다."""

import pytest
from pydantic import ValidationError

from app_core.schema import AdBrief, AdBriefDraft, CopyCandidate, StoreInput

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


# ── 문구 후보 ────────────────────────────────────────────────


def test_헤드라인이_비면_거부한다() -> None:
    with pytest.raises(ValidationError):
        CopyCandidate(headline="")


def test_서브는_없어도_된다() -> None:
    assert CopyCandidate(headline="겨울 감성 크로플").sub == ""
