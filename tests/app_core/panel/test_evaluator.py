"""평가 엔진 테스트 — LLM 응답을 어떻게 거르고 다시 부르는지."""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel import evaluator
from app_core.panel.aggregate import AggregationError
from app_core.panel.evaluator import (
    MAX_EVAL_CALLS,
    build_user_prompt,
    evaluate,
    offered_paths,
)
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


def test_call_count_without_consistency(yeoksam: Panel, shop, brief, copy) -> None:
    """자기일관성을 끄면 한 명당 1콜 + 요약 1콜이다 (07 R4)."""
    client = FakeClient(_reply_by_demo(yeoksam))
    evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

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


# --- 프롬프트 회귀 방지 (2026-08-11 아인님 제보) --------------------------------


def test_prompt_has_no_pipe_placeholder() -> None:
    """세로줄 예시를 넣으면 모델이 그대로 베낀다.

    실측(아인님): 23콜 중 21콜이 `"price|message"` 같은 값을 내서 스키마에서
    탈락했다. 12명 중 1~5명만 살아남아 제품 전체가 막혔다.
    자리표시자는 **실제로 쓸 수 있는 값 하나**여야 한다.
    """
    assert "price|message" not in evaluator.SYSTEM
    assert '"resistance": "price"' in evaluator.SYSTEM


def test_prompt_states_allowed_values_as_prose() -> None:
    """허용값은 예시가 아니라 문장으로 알려준다."""
    assert "넷 중 하나를 그대로 적는다" in evaluator.SYSTEM
    assert "세로줄" in evaluator.SYSTEM


def test_json_example_uses_realistic_values() -> None:
    """`"attention": 0` 같은 자리표시자는 모델을 0점으로 끌어당긴다."""
    assert '"attention": 0,' not in evaluator.SYSTEM
    assert "값은 베끼지 마라" in evaluator.SYSTEM


def test_retry_carries_a_correction_hint(yeoksam: Panel, shop, brief, copy) -> None:
    """`temperature=0` 이라 같은 입력을 다시 보내면 같은 오답이 나온다.

    재시도가 의미를 가지려면 무엇을 어겼는지 알려줘야 한다.
    """
    target = yeoksam.personas[0].demo
    seen: list[str] = []

    def reply(persona_id: str, calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona_id == target:
            if calls.count(target) == 1:
                return {"resistance": "price|message"}  # 세로줄 오답 재현
            return _good(persona)
        return _good(persona)

    class Recording(FakeClient):
        def complete_json(self, system: str, user: str) -> dict:
            if not system.startswith("손님들의 평가를"):
                seen.append(user)
            return super().complete_json(system, user)

    client = Recording(reply)
    result = evaluate(yeoksam, shop, brief, copy, client=client)

    retried = [u for u in seen if "직전 응답이 규칙을 어겼다" in u]
    assert retried, "재시도 프롬프트에 교정 지시가 붙어야 한다"
    assert "하나만" in retried[0]
    assert result.excluded_cnt == 0  # 교정 후 통과


def test_evidence_failure_hint_names_the_path(yeoksam: Panel, shop, brief, copy) -> None:
    """어느 수치가 틀렸는지 짚어줘야 모델이 고칠 수 있다."""
    target = yeoksam.personas[0].demo
    seen: list[str] = []

    def reply(persona_id: str, calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona_id == target and calls.count(target) == 1:
            return _good(persona, evidence=[{"path": "age_share.30", "value": 0.999}])
        return _good(persona)

    class Recording(FakeClient):
        def complete_json(self, system: str, user: str) -> dict:
            if not system.startswith("손님들의 평가를"):
                seen.append(user)
            return super().complete_json(system, user)

    evaluate(yeoksam, shop, brief, copy, client=Recording(reply))
    retried = [u for u in seen if "직전 응답이 규칙을 어겼다" in u]
    assert retried
    assert "age_share.30" in retried[0]


# --- 대조(contrast) 연결 -------------------------------------------------------


def test_contrast_notes_are_carried(yeoksam: Panel, shop, brief, copy) -> None:
    """LLM 없이 나온 대조 문장이 결과에 실려야 한다.

    화면이 `EvaluationResult` 하나만 보면 되도록 설계했으므로, 여기 없으면
    화면이 `contrast()` 를 따로 부르며 features 를 다시 들고 다녀야 한다.
    """
    client = FakeClient(_reply_by_demo(yeoksam))
    result = evaluate(yeoksam, shop, brief, copy, client=client)

    kinds = {n.kind for n in result.contrast_notes}
    assert "composition" in kinds  # 동네 구성은 항상 들어간다
    assert "price" in kinds  # 9,500원을 넣었으므로
    assert all(n.text for n in result.contrast_notes)


def test_contrast_notes_survive_the_evidence_gate(yeoksam: Panel, shop, brief, copy) -> None:
    """대조가 인용한 수치도 근거 대조를 통과해야 한다.

    통과 못 하면 우리가 스스로 만든 문장이 우리 검증기에 걸리는 셈이라,
    사장님에게 보여주는 숫자와 페르소나가 인용하는 숫자가 어긋난 것이다.
    """
    from app_core.panel.evidence import evidence_match

    client = FakeClient(_reply_by_demo(yeoksam))
    result = evaluate(yeoksam, shop, brief, copy, client=client)

    for note in result.contrast_notes:
        assert evidence_match(yeoksam.features, note.evidence), note.kind


def test_contrast_is_llm_free(yeoksam: Panel, shop, brief, copy) -> None:
    """대조는 콜을 쓰지 않는다 — 예산에 영향이 없어야 한다."""
    client = FakeClient(_reply_by_demo(yeoksam))
    evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)
    assert len(client.calls) == len(yeoksam.personas) + 1  # 평가 + 요약뿐


def test_contrast_is_deterministic(yeoksam: Panel, shop, brief, copy) -> None:
    first = evaluate(yeoksam, shop, brief, copy, client=FakeClient(_reply_by_demo(yeoksam)))
    second = evaluate(yeoksam, shop, brief, copy, client=FakeClient(_reply_by_demo(yeoksam)))
    assert [n.text for n in first.contrast_notes] == [n.text for n in second.contrast_notes]


def test_price_note_absent_when_price_is_zero(yeoksam: Panel, shop, copy) -> None:
    """0 원은 '가격 없음'이다. 없는 가격을 동네 객단가와 견주면 안 된다."""
    free = AdBrief(goal="copy", product="크로플", price=0)
    result = evaluate(yeoksam, shop, free, copy, client=FakeClient(_reply_by_demo(yeoksam)))
    assert "price" not in {n.kind for n in result.contrast_notes}


# --- 저항 요인 비중 -----------------------------------------------------------


def test_resistance_share_is_reported(yeoksam: Panel, shop, brief, copy) -> None:
    """라벨만으로는 '얼마나' 걸리는지 화면이 못 쓴다."""
    labels = ["price"] * 6 + ["message"] * 3
    by_demo = {p.demo: p for p in yeoksam.personas}
    order = [p.demo for p in yeoksam.personas]

    def reply(demo: str, _calls: list[str]) -> dict[str, Any]:
        i = order.index(demo)
        return _good(by_demo[demo], resistance=labels[i] if i < len(labels) else "none")

    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply))

    assert set(result.resistance_share) == {"price", "message"}
    assert sum(result.resistance_share.values()) == pytest.approx(1.0, abs=1e-3)
    assert result.resistance_share["price"] > result.resistance_share["message"]
    assert result.top_resistance[0] == "price"


def test_resistance_share_empty_when_nobody_objects(yeoksam: Panel, shop, brief, copy) -> None:
    client = FakeClient(_reply_by_demo(yeoksam, resistance="none"))
    result = evaluate(yeoksam, shop, brief, copy, client=client)
    assert result.resistance_share == {}
    assert result.top_resistance == []


# --- 예외 격리·마감·에코 (2026-08-11 자체 공격에서 발견) ------------------------


def test_client_exception_excludes_only_that_persona(yeoksam: Panel, shop, brief, copy) -> None:
    """네트워크 순단 한 건이 12명 전체를 죽이면 안 된다.

    스레드 안 예외는 `Future.result()` 에서 다시 터진다 — 방벽이 없으면
    통과한 11명의 결과까지 통째로 버려진다. 실제로 죽는 것을 확인하고 막았다.
    """
    target = yeoksam.personas[0].demo

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        if persona_id == target:
            raise ConnectionError("네트워크 순단")
        return _good({p.demo: p for p in yeoksam.personas}[persona_id])

    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply))

    assert result.excluded_cnt == 1
    assert yeoksam.personas[0].persona_id in result.excluded_ids
    assert len(result.persona_comments) == len(yeoksam.personas) - 1


def test_deadline_flags_timed_out_personas(yeoksam: Panel, shop, brief, copy) -> None:
    """마감을 넘긴 페르소나는 실패로 세고, 신뢰도 사유에 남는다.

    부분 패널의 점수를 온전한 패널인 척 보여주지 않기 위해서다.
    """
    import time as _time

    target = yeoksam.personas[0].demo

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        if persona_id == target:
            _time.sleep(0.8)
        return _good({p.demo: p for p in yeoksam.personas}[persona_id])

    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply), deadline_s=0.2)

    assert yeoksam.personas[0].persona_id in result.excluded_ids
    assert any("시간 초과" in r for r in result.confidence_reasons)
    assert result.confidence == "low"


def test_all_timed_out_raises(yeoksam: Panel, shop, brief, copy) -> None:
    import time as _time

    def reply(_persona_id: str, _calls: list[str]) -> dict[str, Any]:
        _time.sleep(0.5)
        return {}

    with pytest.raises(AggregationError):
        evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply), deadline_s=0.05)


def test_elapsed_ms_is_measured(yeoksam: Panel, shop, brief, copy) -> None:
    """R4 30초 예산을 지켰는지 결과가 스스로 말해야 한다."""
    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(_reply_by_demo(yeoksam)))
    assert result.elapsed_ms >= 0


def test_persona_id_echo_is_tolerated(yeoksam: Panel, shop, brief, copy) -> None:
    """모델이 persona_id 를 에코하면 TypeError 로 죽고 재시도가 낭비됐다.

    서버 값이 이기고, 에코는 벗겨낸다. 재시도도 없어야 한다.
    """
    by_demo = {p.demo: p for p in yeoksam.personas}

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        payload = _good(by_demo[persona_id])
        payload["persona_id"] = "spoofed"
        return payload

    client = FakeClient(reply)
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert result.excluded_cnt == 0
    assert len(client.calls) == len(yeoksam.personas) + 1  # 재시도 없음
    assert "spoofed" not in {c.persona_id for c in result.persona_comments}


def test_runaway_comment_is_truncated_not_retried(yeoksam: Panel, shop, brief, copy) -> None:
    """10KB 코멘트는 자르고 받는다 — 좋은 답이 길다는 이유로 재시도(유료)하지 않는다."""
    by_demo = {p.demo: p for p in yeoksam.personas}

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        return _good(by_demo[persona_id], comment="가" * 10000)

    client = FakeClient(reply)
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert result.excluded_cnt == 0
    assert all(len(c.comment) <= 300 for c in result.persona_comments)
    assert len(client.calls) == len(yeoksam.personas) + 1  # 재시도 없음


def test_summary_failure_does_not_void_scores(yeoksam: Panel, shop, brief, copy) -> None:
    """요약은 부가물이다 — 요약 콜이 터져도 이미 끝난 평가를 버리면 안 된다."""

    class Boom(FakeClient):
        def complete_json(self, system: str, user: str) -> dict:
            if system.startswith("손님들의 평가를"):
                raise RuntimeError("요약 실패")
            return super().complete_json(system, user)

    result = evaluate(yeoksam, shop, brief, copy, client=Boom(_reply_by_demo(yeoksam)))

    assert result.suggestions == []
    assert result.scores
    assert result.excluded_cnt == 0


# --- 정확도: 근거의 질 · 척도 앵커 · 자기일관성 (V6) ---------------------------


def test_evidence_must_come_from_this_persona(yeoksam: Panel, shop, brief, copy) -> None:
    """값이 맞아도 **그 손님에게 보여주지 않은** 숫자는 근거가 아니다.

    이게 없으면 60대 손님이 "30대가 38%라서"를 근거로 대도 통과한다.
    인용은 정확하지만 자기 판단의 근거는 아니다.
    """
    old = next(p for p in yeoksam.personas if p.demo.startswith("60"))
    foreign = "age_share.30"
    assert foreign not in offered_paths(yeoksam.features, old)

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona.persona_id == old.persona_id:
            # 값 자체는 실제값과 정확히 일치한다 — 그래도 탈락해야 한다
            return _good(
                persona,
                evidence=[{"path": foreign, "value": yeoksam.features.age_share["30"]}],
            )
        return _good(persona)

    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply), consistency_k=1)
    assert old.persona_id in result.excluded_ids


def test_off_prompt_hint_tells_the_model_what_to_use(yeoksam: Panel, shop, brief, copy) -> None:
    """재시도 지시가 "값이 틀렸다"가 아니라 "목록에 없다"여야 고칠 수 있다."""
    old = next(p for p in yeoksam.personas if p.demo.startswith("60"))
    seen: list[str] = []

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona.persona_id == old.persona_id:
            return _good(
                persona,
                evidence=[{"path": "age_share.30", "value": yeoksam.features.age_share["30"]}],
            )
        return _good(persona)

    class Recording(FakeClient):
        def complete_json(self, system: str, user: str) -> dict:
            if not system.startswith("손님들의 평가를"):
                seen.append(user)
            return super().complete_json(system, user)

    evaluate(yeoksam, shop, brief, copy, client=Recording(reply), consistency_k=1)
    hints = [u for u in seen if "직전 응답이 규칙을 어겼다" in u]
    assert hints
    assert "목록에 적힌 것만" in hints[0] or "그 목록에 적힌 것만" in hints[0]


def test_offered_paths_match_the_prompt(yeoksam: Panel) -> None:
    """프롬프트와 게이트가 같은 목록을 봐야 한다 — 따로 관리하면 어긋난다."""
    for persona in yeoksam.personas:
        block = evaluator._feature_lines(yeoksam.features, persona)
        in_prompt = {line.split(" = ")[0].removeprefix("- ") for line in block.splitlines()}
        assert in_prompt == offered_paths(yeoksam.features, persona), persona.persona_id


def test_prompt_gives_score_anchors() -> None:
    """0~100 만 주면 척도가 사람마다 달라진다 — 구간 뜻을 준다."""
    assert "점수 기준" in evaluator.SYSTEM
    assert "81~100" in evaluator.SYSTEM
    assert "60점대에 몰아 쓰지 마라" in evaluator.SYSTEM


def test_consistency_uses_median_not_mean(yeoksam: Panel, shop, brief, copy) -> None:
    """한 번의 튐이 결과를 흔들면 안 된다.

    53 / 53 / 63 → 중앙값 53. 평균이면 56.3 으로 끌려간다
    (아인님 실측에서 실제로 나온 값이다).
    """
    top = max(yeoksam.personas, key=lambda p: p.weight)
    scores = {top.demo: [53, 53, 63]}

    def reply(persona_id: str, calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona_id in scores:
            n = calls.count(persona_id) - 1
            value = scores[persona_id][min(n, 2)]
            return _good(persona, attention=value, message=value, intent=value)
        return _good(persona, attention=53, message=53, intent=53)

    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply), consistency_k=3)
    assert result.scores["attention"] == 53.0


def test_consistency_respects_the_call_budget(yeoksam: Panel, shop, brief, copy) -> None:
    """반복이 예산을 넘으면 안 된다 — 요약 1콜까지 계산에 넣는다 (07 R4)."""
    client = FakeClient(_reply_by_demo(yeoksam))
    evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=3)
    assert len(client.calls) <= MAX_EVAL_CALLS


def test_consistency_goes_to_heaviest_personas_first(yeoksam: Panel) -> None:
    """남는 콜은 가중 평균을 실제로 움직이는 쪽에 쓴다."""
    targets = sorted(yeoksam.personas, key=lambda p: -p.weight)
    plan = evaluator._sample_plan(targets, 3)

    assert plan[targets[0].persona_id] >= plan[targets[-1].persona_id]
    assert sum(plan.values()) <= MAX_EVAL_CALLS - 1


def test_consistency_can_be_disabled(yeoksam: Panel) -> None:
    targets = sorted(yeoksam.personas, key=lambda p: -p.weight)
    assert set(evaluator._sample_plan(targets, 1).values()) == {1}


def test_merged_comment_is_a_real_response(yeoksam: Panel, shop, brief, copy) -> None:
    """합성 문장을 만들면 아무도 하지 않은 말이 된다 — 실제 응답 중 하나를 쓴다."""
    top = max(yeoksam.personas, key=lambda p: p.weight)
    said = {"첫 번째 말", "두 번째 말", "세 번째 말"}

    def reply(persona_id: str, calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        payload = _good(persona)
        if persona.persona_id == top.persona_id:
            payload["comment"] = list(said)[min(calls.count(persona_id) - 1, 2)]
        return payload

    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply), consistency_k=3)
    comment = next(c.comment for c in result.persona_comments if c.persona_id == top.persona_id)
    assert comment in said


def test_one_bad_sample_does_not_lose_the_persona(yeoksam: Panel, shop, brief, copy) -> None:
    """표본 하나가 예외로 죽어도 나머지로 합쳐야 한다."""
    top = max(yeoksam.personas, key=lambda p: p.weight)

    def reply(persona_id: str, calls: list[str]) -> dict[str, Any]:
        persona = {p.demo: p for p in yeoksam.personas}[persona_id]
        if persona.persona_id == top.persona_id and calls.count(persona_id) == 2:
            raise ConnectionError("두 번째 표본만 순단")
        return _good(persona)

    result = evaluate(yeoksam, shop, brief, copy, client=FakeClient(reply), consistency_k=3)
    assert result.excluded_cnt == 0
    assert top.persona_id in {c.persona_id for c in result.persona_comments}
