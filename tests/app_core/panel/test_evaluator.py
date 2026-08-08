"""평가 엔진 테스트 — LLM 응답을 어떻게 거르고 다시 부르는지."""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel import evaluator
from app_core.panel.aggregate import AggregationError
from app_core.panel.evaluator import MAX_EVAL_CALLS, build_user_prompt, evaluate
from app_core.panel.schemas import Panel, Persona
from app_core.schema import AdBrief, CopyCandidate, Store, StoreInput

AD_ID = "ad-001"


@pytest.fixture
def brief() -> AdBrief:
    return AdBrief(
        goal="copy",
        product="크로플",
        price=9500,
        situation="신메뉴",
        tone="따뜻하게",
    )


@pytest.fixture
def copy() -> CopyCandidate:
    return CopyCandidate(headline="오후 3시의 크로플", sub="갓 구운 겉바속촉")


@pytest.fixture
def shop() -> Store:
    base = StoreInput(industry="cafe", name="연남 크로플", address="서울시 강남구 역삼동 1")
    return Store(**base.model_dump(), id=1, user_id=1)


class FakeClient:
    """페르소나별 응답을 지정한다. 호출 순서·횟수도 기록한다."""

    def __init__(self, reply: Any = None, summary: list[str] | None = None) -> None:
        self._reply = reply
        self._summary = summary if summary is not None else ["묶음가로 제시해보세요"]
        self.calls: list[str] = []

    def complete_json(self, system: str, user: str) -> dict:
        if system.startswith("손님들의 평가를"):
            self.calls.append("summary")
            return {"suggestions": self._summary}

        persona_id = user.split("## 나\n")[1].split(".")[0]
        self.calls.append(persona_id)
        if callable(self._reply):
            return self._reply(persona_id, self.calls)
        return dict(self._reply or {})


def _good(persona: Persona, **over: Any) -> dict[str, Any]:
    """근거 대조를 통과하는 정상 응답."""
    payload: dict[str, Any] = {
        "attention": 70,
        "message": 65,
        "intent": 60,
        "resistance": "none",
        "resistance_detail": "",
        "comment": f"{persona.demo} 한마디",
        "evidence": [{"path": r.path, "value": r.value} for r in persona.evidence],
    }
    payload.update(over)
    return payload


def _reply_by_demo(panel: Panel, **over: Any):
    by_demo = {p.demo: p for p in panel.personas}

    def _fn(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        return _good(by_demo[persona_id], **over)

    return _fn


# --- 정상 경로 -------------------------------------------------------------


def test_all_personas_evaluated(yeoksam: Panel, shop, brief, copy) -> None:
    client = FakeClient(_reply_by_demo(yeoksam))
    result = evaluate(yeoksam, shop, brief, copy, ad_id=AD_ID, client=client)

    assert result.ad_id == AD_ID
    assert result.scores == {"attention": 70.0, "message": 65.0, "intent": 60.0}
    assert result.excluded_cnt == 0
    assert len(result.persona_comments) == len(yeoksam.personas)


def test_call_count_is_one_per_persona_plus_summary(yeoksam: Panel, shop, brief, copy) -> None:
    """콜 예산이 걸려 있다 — 한 명당 1콜 + 요약 1콜이어야 한다 (07 R4)."""
    client = FakeClient(_reply_by_demo(yeoksam))
    evaluate(yeoksam, shop, brief, copy, client=client)

    assert len(client.calls) == len(yeoksam.personas) + 1
    assert client.calls.count("summary") == 1
    assert len(yeoksam.personas) <= MAX_EVAL_CALLS


def test_suggestions_can_be_turned_off(yeoksam: Panel, shop, brief, copy) -> None:
    """아인님 합의 전까지 끌 수 있어야 한다."""
    client = FakeClient(_reply_by_demo(yeoksam))
    result = evaluate(yeoksam, shop, brief, copy, client=client, summarize=False)

    assert result.suggestions == []
    assert "summary" not in client.calls


def test_suggestions_are_capped_at_three(yeoksam: Panel, shop, brief, copy) -> None:
    client = FakeClient(_reply_by_demo(yeoksam), summary=["a", "b", "c", "d", "e"])
    result = evaluate(yeoksam, shop, brief, copy, client=client)
    assert len(result.suggestions) == 3


def test_blank_suggestions_are_dropped(yeoksam: Panel, shop, brief, copy) -> None:
    client = FakeClient(_reply_by_demo(yeoksam), summary=["  ", "쓸 만한 제안", ""])
    result = evaluate(yeoksam, shop, brief, copy, client=client)
    assert result.suggestions == ["쓸 만한 제안"]


# --- 두 관문 ---------------------------------------------------------------


def test_broken_schema_is_retried_once_then_excluded(yeoksam: Panel, shop, brief, copy) -> None:
    """스키마가 깨지면 1회만 다시 부르고, 또 깨지면 뺀다 (07 §8)."""
    target = yeoksam.personas[0].demo

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        if persona_id == target:
            return {"attention": 999}  # 범위 위반 → 스키마 탈락
        return _good({p.demo: p for p in yeoksam.personas}[persona_id])

    client = FakeClient(reply)
    result = evaluate(yeoksam, shop, brief, copy, client=client)

    assert client.calls.count(target) == 2  # 최초 1 + 재시도 1
    assert result.excluded_cnt == 1
    assert yeoksam.personas[0].persona_id in result.excluded_ids


def test_invented_number_is_retried_then_excluded(yeoksam: Panel, shop, brief, copy) -> None:
    """수치를 지어내면 근거 대조에서 걸린다 — 이 게이트가 이 모듈의 핵심이다."""
    target = yeoksam.personas[0].demo

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona_id == target:
            return _good(persona, evidence=[{"path": "age_share.30", "value": 0.999}])
        return _good(persona)

    client = FakeClient(reply)
    result = evaluate(yeoksam, shop, brief, copy, client=client)

    assert client.calls.count(target) == 2
    assert result.excluded_cnt == 1


def test_retry_can_succeed(yeoksam: Panel, shop, brief, copy) -> None:
    """첫 응답이 깨져도 두 번째가 멀쩡하면 살린다."""
    target = yeoksam.personas[0].demo

    def reply(persona_id: str, calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona_id == target and calls.count(target) == 1:
            return {}  # 첫 콜만 빈 응답
        return _good(persona)

    client = FakeClient(reply)
    result = evaluate(yeoksam, shop, brief, copy, client=client)

    assert client.calls.count(target) == 2
    assert result.excluded_cnt == 0


def test_all_failed_raises(yeoksam: Panel, shop, brief, copy) -> None:
    """스텁 프로필처럼 전부 빈 응답이면 집계할 게 없다."""
    client = FakeClient({})
    with pytest.raises(AggregationError):
        evaluate(yeoksam, shop, brief, copy, client=client)


def test_no_summary_call_when_everything_failed(yeoksam: Panel, shop, brief, copy) -> None:
    """통과분이 없으면 요약 콜을 낭비하지 않는다."""
    client = FakeClient({})
    with pytest.raises(AggregationError):
        evaluate(yeoksam, shop, brief, copy, client=client)
    assert "summary" not in client.calls


# --- 프롬프트 --------------------------------------------------------------


def test_prompt_only_offers_citable_numbers(yeoksam: Panel, shop, brief, copy) -> None:
    """인용 금지 필드를 프롬프트에 주면 모델이 그걸 인용하고 전부 탈락한다."""
    persona = yeoksam.personas[0]
    prompt = build_user_prompt(persona, yeoksam.features, shop, brief, copy)

    assert "match_distance_m" not in prompt
    assert "demo_coverage" not in prompt
    for ref in persona.evidence:
        assert ref.path in prompt


def test_prompt_hides_price_when_zero(yeoksam: Panel, shop, copy) -> None:
    """0 원은 '가격 없음'이다. 없는 가격을 평가하게 하면 안 된다."""
    free = AdBrief(goal="copy", product="크로플", price=0)
    prompt = build_user_prompt(yeoksam.personas[0], yeoksam.features, shop, free, copy)
    assert "광고에 없음" in prompt
    assert "0원" not in prompt


def test_prompt_carries_narrative_and_ad(yeoksam: Panel, shop, brief, copy) -> None:
    persona = yeoksam.personas[0]
    prompt = build_user_prompt(persona, yeoksam.features, shop, brief, copy)

    assert persona.narrative in prompt
    assert copy.headline in prompt
    assert brief.product in prompt
    assert shop.industry_label in prompt


def test_visual_resistance_is_forbidden_in_prompt() -> None:
    """이미지를 안 보여주므로 visual 저항은 근거 없는 판정이 된다."""
    assert "visual 은 고르지 마라" in evaluator.SYSTEM
