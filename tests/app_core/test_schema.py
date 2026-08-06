"""주문서 스키마 — 틀린 값이 여기서 걸리는지 검증한다."""

import pytest
from pydantic import ValidationError

from app_core import registry
from app_core.schema import AdBrief, AdBriefDraft, Evaluation, PriceItem, StoreProfile

CAFE = "cafe"
FEED = "insta_feed"
WARM = "warm"


def profile(**kw) -> StoreProfile:
    return StoreProfile(**{"industry": CAFE, "address": "서울시 마포구 연남동 1-2", **kw})


def brief(**kw) -> AdBrief:
    base = {
        "session_id": "sess-1",
        "ad_id": "ad-1",
        "store": profile(),
        "goal": "image",
        "format": FEED,
        "style": WARM,
        "product": "크로플",
    }
    return AdBrief(**{**base, **kw})


# ── 가게 정보 ────────────────────────────────────────────────


def test_정상_등록() -> None:
    p = profile(name="○○카페", phone="02-000-0000")
    assert p.industry == CAFE and p.name == "○○카페"


def test_모르는_업종은_거부한다() -> None:
    """LLM 이 목록에 없는 업종을 지어내도 여기서 막힌다."""
    with pytest.raises(ValidationError, match="모르는 업종"):
        profile(industry="우주정거장")


def test_서울_밖_주소는_거부한다() -> None:
    """상권 데이터가 서울 기준이라, 나중에 조회 단계에서 실패하기 전에 막는다."""
    with pytest.raises(ValidationError, match="서울"):
        profile(address="부산광역시 해운대구")


def test_주소_앞뒤_공백은_정리한다() -> None:
    assert profile(address="  서울시 강남구 대치동  ").address == "서울시 강남구 대치동"


def test_상호와_연락처는_없어도_된다() -> None:
    p = profile()
    assert p.name is None and p.phone is None


def test_모르는_필드는_거부한다() -> None:
    """오타로 만든 필드가 조용히 무시되면 안 된다."""
    with pytest.raises(ValidationError):
        profile(addres="서울시 마포구")


# ── 주문서 ──────────────────────────────────────────────────


def test_필수가_다_차면_생성_가능하다() -> None:
    b = brief()
    assert b.product == "크로플" and b.store.industry == CAFE


@pytest.mark.parametrize("field,bad", [("format", "a3_poster"), ("style", "네온사인")])
def test_레지스트리에_없는_값은_거부한다(field: str, bad: str) -> None:
    with pytest.raises(ValidationError, match="모르는"):
        brief(**{field: bad})


def test_상품명이_비면_거부한다() -> None:
    with pytest.raises(ValidationError):
        brief(product="")


def test_목적은_두_가지뿐이다() -> None:
    with pytest.raises(ValidationError):
        brief(goal="video")


# ── 계산되는 값 ─────────────────────────────────────────────


@pytest.mark.parametrize("has_photo,expected", [(True, "preserve"), (False, "scene")])
def test_모드는_사진_유무로_정해진다(has_photo: bool, expected: str) -> None:
    """사용자는 모드를 고르지 않는다."""
    assert brief(has_photo=has_photo).mode == expected


def test_법령_태그는_업종과_규격의_합집합이다() -> None:
    b = brief()
    industry = registry.by_id(registry.industries(), CAFE)
    fmt = registry.by_id(registry.formats(), FEED)
    assert set(b.legal_tags) == registry.legal_tags_for(industry, fmt)


def test_넘길_때_계산값이_함께_들어간다() -> None:
    """받는 쪽이 각자 계산하면 값이 어긋난다."""
    payload = brief(has_photo=True).to_payload()
    assert payload["mode"] == "preserve"
    assert "legal_tags" in payload
    assert payload["store"]["industry"] == CAFE


# ── 가격·되먹임 ─────────────────────────────────────────────


def test_가격은_항목명과_값이_모두_있어야_한다() -> None:
    """AI 가 만들지 않는 값이므로 반쪽짜리로 들어오면 안 된다."""
    with pytest.raises(ValidationError):
        PriceItem(name="크로플", price="")


def test_가격_목록은_기본이_비어있다() -> None:
    assert brief().items == []


def test_이전_평가를_받아_재생성할_수_있다() -> None:
    b = brief(prev_evaluation=Evaluation(top_resistance=["비싸 보임"], suggestions=["가격 크게"]))
    assert b.prev_evaluation is not None
    assert b.prev_evaluation.top_resistance == ["비싸 보임"]


def test_평가가_없는_것이_기본이다() -> None:
    assert brief().prev_evaluation is None


# ── 대화 초안 (AdBriefDraft) ────────────────────────────────


def test_빈_초안은_필수가_전부_비어있다() -> None:
    assert AdBriefDraft().missing() == ["goal", "style", "product"]


def test_한_슬롯만_차도_missing에서_빠진다() -> None:
    draft = AdBriefDraft(product="크로플")
    assert draft.missing() == ["goal", "style"]


def test_다_차면_missing이_빈다() -> None:
    draft = AdBriefDraft(goal="image", style=WARM, product="크로플")
    assert draft.missing() == []


def test_모르는_스타일은_초안에서도_거부한다() -> None:
    with pytest.raises(ValidationError, match="모르는"):
        AdBriefDraft(style="네온사인")


def test_이번_턴에_안_나온_슬롯은_이전_값을_유지한다() -> None:
    """ "아까 카페라고 했잖아"를 매번 다시 말하게 하지 않는다."""
    draft = AdBriefDraft(product="크로플").merge(AdBriefDraft(style=WARM))
    assert draft.product == "크로플" and draft.style == WARM


def test_새_턴이_같은_슬롯을_다시_말하면_덮어쓴다() -> None:
    draft = AdBriefDraft(style=WARM).merge(AdBriefDraft(style="bold"))
    assert draft.style == "bold"


def test_빈_값으로는_기존_값을_지우지_않는다() -> None:
    """LLM이 이번 턴에 못 뽑아낸 필드를 빈 문자열로 돌려줘도 이전 값이 살아있어야 한다."""
    draft = AdBriefDraft(product="크로플").merge(AdBriefDraft(product=""))
    assert draft.product == "크로플"


def test_다_차면_주문서로_승격한다() -> None:
    draft = AdBriefDraft(goal="image", style=WARM, product="크로플")
    b = draft.to_brief(session_id="sess-1", ad_id="ad-1", store=profile())
    assert b.product == "크로플" and b.format == FEED


def test_안_찼는데_승격하려면_거부한다() -> None:
    with pytest.raises(ValueError, match="아직 안 찬"):
        AdBriefDraft(product="크로플").to_brief(session_id="sess-1", ad_id="ad-1", store=profile())


def test_초안도_모르는_필드는_거부한다() -> None:
    with pytest.raises(ValidationError):
        AdBriefDraft(styel=WARM)
