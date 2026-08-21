"""평가 엔진 테스트 — LLM 응답을 어떻게 거르고 다시 부르는지."""

from __future__ import annotations

import inspect
from typing import Any, get_args

import pytest

from app_core.panel import evaluator
from app_core.panel.aggregate import AggregationError
from app_core.panel.contrast import price_visible
from app_core.panel.evaluator import (
    FOLLOW_UP_CALLS,
    MAX_EVAL_CALLS,
    _fallback_suggestions,
    build_user_prompt,
    evaluate,
    offered_paths,
)
from app_core.panel.schemas import (
    ContrastNote,
    EvaluationResult,
    Panel,
    Persona,
    PersonaComment,
    Resistance,
)
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

    def __init__(
        self,
        reply: Any = None,
        summary: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> None:
        self._reply = reply
        self._summary = summary if summary is not None else ["묶음가로 제시해보세요"]
        #: 걸림돌 분류 콜의 응답. None 이면 손님이 고른 라벨을 그대로 둔다.
        self._labels = labels
        self.calls: list[str] = []

    def complete_json(self, system: str, user: str) -> dict:
        if system.startswith("손님들의 평가를"):
            self.calls.append("summary")
            return {"suggestions": self._summary}

        if system.startswith("손님이 남긴 한 줄을"):
            self.calls.append("resistance")
            # 기본은 **분류 안 함** — 손님이 고른 라벨을 그대로 두어야
            # 기존 테스트의 의도(라벨을 직접 지정)가 유지된다.
            if not self._labels:
                return {}
            return {"labels": {str(i + 1): lab for i, lab in enumerate(self._labels)}}

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
    """자기일관성을 끄면 한 명당 1콜 + 걸림돌 분류 1콜 + 요약 1콜이다 (07 R4)."""
    client = FakeClient(_reply_by_demo(yeoksam))
    evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert len(client.calls) == len(yeoksam.personas) + 2
    assert client.calls.count("summary") == 1
    assert client.calls.count("resistance") == 1
    assert len(yeoksam.personas) <= MAX_EVAL_CALLS


def test_suggestions_can_be_turned_off(yeoksam: Panel, shop, brief, copy) -> None:
    """아인님 합의 전까지 끌 수 있어야 한다."""
    client = FakeClient(_reply_by_demo(yeoksam))
    result = evaluate(yeoksam, shop, brief, copy, client=client, summarize=False)

    assert "summary" not in client.calls
    # 요약 **콜**을 끄는 플래그다. 제안 자체가 비면 재생성이 죽으므로
    # (`test_suggestions_never_empty`) 집계에서 뽑은 한 줄이 대신 들어간다.
    assert result.suggestions == _fallback_suggestions(result)


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
    """통과분이 없으면 뒤따르는 콜을 낭비하지 않는다."""
    client = FakeClient({})
    with pytest.raises(AggregationError):
        evaluate(yeoksam, shop, brief, copy, client=client)
    assert "summary" not in client.calls
    assert "resistance" not in client.calls


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


#: 프롬프트가 "넷 중 하나" 처럼 개수를 말할 때 쓰는 우리말 수사.
_COUNT_KO = {3: "셋", 4: "넷", 5: "다섯", 6: "여섯"}


def test_prompt_states_allowed_values_as_prose() -> None:
    """허용값은 예시가 아니라 문장으로 알려준다.

    개수를 `Resistance` 에서 유도한다. 2026-08-14 에 라벨을 하나 늘리면서
    "넷 중"을 "다섯 중"으로 고쳤는데 이 테스트가 옛 숫자를 붙들고 있었다 —
    글자를 박아두면 라벨과 프롬프트가 조용히 어긋난다.
    """
    from app_core.panel.schemas import Resistance

    # `visual` 은 광고 이미지를 안 보므로 고를 수 없다고 프롬프트가 못박는다.
    selectable = [lab for lab in get_args(Resistance) if lab != "visual"]
    assert f"{_COUNT_KO[len(selectable)]} 중 하나를 그대로 적는다" in evaluator.SYSTEM
    assert "세로줄" in evaluator.SYSTEM

    # 목록에 실제로 그 개수만큼 적혀 있어야 한다.
    block = evaluator.SYSTEM.split("**resistance**")[1].split("**evidence**")[0]
    for label in selectable:
        assert label in block, f"프롬프트 목록에 {label} 이 없다"
    assert "visual 은 고르지 마라" in block


def test_json_example_uses_realistic_values() -> None:
    """숫자는 실제 값으로, 글은 자리표시로 — 둘을 다르게 다룬다.

    `"attention": 0` 같은 자리표시자는 모델을 0점으로 끌어당긴다. 반대로
    실제 값을 적어 두면 그 값 근처로 몰린다 — 예시는 답을 묶지만 **재현성도
    준다**(아인님 실측 2026-08-14: 예시를 통째로 빼면 변별력이 +5.9/-4.4 로
    부호까지 바뀐다). 그래서 숫자는 남긴다.

    글은 다르다. 예시의 `comment` 가 가격 이야기라 답도 가격으로 쏠렸다
    (아인님 실측 2026-08-17: 값 하나 바꾸자 4케이스 중 3개가 뒤집혔다).
    글은 형태만 보여주고 내용은 비운다.

    `resistance` 는 글이 아니라 **enum** 이다 — 자리표시를 넣으면 그걸 베껴
    Literal 검증에서 탈락한다(세로줄 사고). 그래서 실제 값을 유지한다.
    세 부류의 규칙이 다르다: 숫자는 실제 값, enum 은 실제 값, 글은 자리표시.
    """
    assert '"attention": 0,' not in evaluator.SYSTEM
    assert '"attention": 62,' in evaluator.SYSTEM  # 숫자는 실제 값
    assert '"resistance": "price"' in evaluator.SYSTEM  # enum 은 실제 값
    assert "값은 베끼지 마라" in evaluator.SYSTEM


def test_persona_example_names_no_resistance_label() -> None:
    """예시가 라벨 하나를 지목하면 그게 답이 된다.

    `resistance_detail` · `comment` 도 마찬가지다 — 셋 다 가격 이야기였다.
    분류 콜이 최종 라벨을 정하지만 **오염이 코멘트를 타고 넘어간다**
    (아인님 지적: 뜻 없는 문구에도 message 가 0명이었다).
    """
    example = evaluator.SYSTEM.split("아래 JSON 형식으로만 답해라.")[1]

    # `resistance` 는 Literal 이라 자리표시자를 그대로 베끼면 스키마에서
    # 탈락한다 — 세로줄 버그(2026-08-07, 23콜 중 21콜 사망)와 같은 자리다.
    # 그래서 라벨은 실제 값을 남기고, **글만** 비운다.
    assert '"resistance": "price"' in example

    for field in ("resistance_detail", "comment"):
        line = next(ln for ln in example.splitlines() if field in ln)
        assert "<" in line and ">" in line, f"{field} 이 자리표시가 아니다"
        assert "원" not in line, f"{field} 에 금액이 남아 있다"
        assert "가격" not in line, f"{field} 이 가격을 지목한다"


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
    # 금액이 실려야 가격 대조가 붙는다 (2026-08-20 `price_visible`)
    priced = CopyCandidate(headline=f"크로플 {brief.price:,}원", sub=copy.sub)
    result = evaluate(yeoksam, shop, brief, priced, client=client)

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
    # 대조는 콜을 안 쓴다 — 평가 + 뒤따르는 콜(분류·요약)뿐이다.
    assert len(client.calls) == len(yeoksam.personas) + FOLLOW_UP_CALLS


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
    assert len(client.calls) == len(yeoksam.personas) + FOLLOW_UP_CALLS  # 재시도 없음
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
    assert len(client.calls) == len(yeoksam.personas) + FOLLOW_UP_CALLS  # 재시도 없음


def test_summary_failure_does_not_void_scores(yeoksam: Panel, shop, brief, copy) -> None:
    """요약은 부가물이다 — 요약 콜이 터져도 이미 끝난 평가를 버리면 안 된다."""

    class Boom(FakeClient):
        def complete_json(self, system: str, user: str) -> dict:
            if system.startswith("손님들의 평가를"):
                raise RuntimeError("요약 실패")
            return super().complete_json(system, user)

    result = evaluate(yeoksam, shop, brief, copy, client=Boom(_reply_by_demo(yeoksam)))

    assert result.scores, "요약이 터졌다고 점수를 버리면 안 된다"
    assert result.suggestions == _fallback_suggestions(result)
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
    # 2026-08-14: "60점대에 몰아 쓰지 마라" 는 지웠다. 피하라고 이름 붙인 구간
    # 바로 아래(50점대)로 모델이 내려앉았고, 그게 61 문턱 밑이라 걸림돌을
    # 억지로 고르게 만들었다 (아인님 실측: intent 19건 중 16건이 61 미만).
    assert "60점대에 몰아 쓰지 마라" not in evaluator.SYSTEM
    assert "세 지표를 비슷한 숫자로 채우지 마라" in evaluator.SYSTEM


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


# --- 제안이 금액을 지어내지 못하게 (2026-08-11 아인님 실측 제보) ----------------


def _suggest(client_reply, texts: list[str] | None = None):
    """요약 콜이 `texts` 를 내놓고, 요약 프롬프트를 기록하는 가짜 클라이언트."""

    class Summarizer(FakeClient):
        summary_prompt = ""

        def complete_json(self, system: str, user: str) -> dict:
            if system.startswith("손님들의 평가를"):
                self.calls.append("summary")
                self.summary_prompt = user
                return {"suggestions": texts or []}
            return super().complete_json(system, user)

    return Summarizer(client_reply)


def test_invented_amount_is_dropped(yeoksam: Panel, shop, copy) -> None:
    """실측: 광고가 6,000원인데 "9,500원에서 8,500원으로"가 3회 중 3회 나왔다.

    페르소나 응답은 근거 대조를 거치는데 제안만 그냥 통과하면, 검증받지 않은
    숫자가 사장님 화면에 뜬다.
    """
    brief = AdBrief(goal="copy", product="크로플", price=6000)
    client = _suggest(
        _reply_by_demo(yeoksam),
        [
            "크로플 가격을 '9,500원'에서 '8,500원'으로 조정해보세요",
            "가격을 낮추기보다 세트 구성으로 묶어 보여주세요",
        ],
    )
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)
    assert result.suggestions == ["가격을 낮추기보다 세트 구성으로 묶어 보여주세요"]


def test_real_price_may_be_quoted(yeoksam: Panel, shop, copy) -> None:
    """게이트가 과하면 쓸 만한 제안까지 사라진다 — 실제 가격은 인용 가능해야 한다.

    ⚠️ **문구에 금액이 실려 있어야 한다.** 2026-08-20 부터 "가격이 있는 광고"는
    사장님이 입력했는지가 아니라 **광고에 보이는지**로 정한다 (`contrast.price_visible`).
    입력만 하고 문구에 안 실리면 손님은 그 값을 모르므로 가격 축을 닫는다.
    """
    brief = AdBrief(goal="copy", product="크로플", price=6000)
    priced = CopyCandidate(headline="크로플 6,000원", sub=copy.sub)
    client = _suggest(_reply_by_demo(yeoksam), ["6,000원이라는 점을 헤드라인에 넣어보세요"])
    result = evaluate(yeoksam, shop, brief, priced, client=client, consistency_k=1)
    assert result.suggestions == ["6,000원이라는 점을 헤드라인에 넣어보세요"]


def test_avg_ticket_may_be_quoted(yeoksam: Panel, shop, copy) -> None:
    brief = AdBrief(goal="copy", product="크로플", price=6000)
    avg = yeoksam.features.avg_ticket
    client = _suggest(
        _reply_by_demo(yeoksam), [f"이 동네 평균 {avg:,}원보다 싸다는 점을 알려보세요"]
    )
    assert evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1).suggestions


def test_summary_prompt_carries_the_real_price(yeoksam: Panel, shop, copy) -> None:
    """지어낼 이유를 없애는 것이 1차 방어다 — 게이트는 2차다."""
    brief = AdBrief(goal="copy", product="크로플", price=6000)
    priced = CopyCandidate(headline="크로플 6,000원", sub=copy.sub)
    client = _suggest(_reply_by_demo(yeoksam), [])
    evaluate(yeoksam, shop, brief, priced, client=client, consistency_k=1)

    assert "6,000원" in client.summary_prompt
    assert f"{yeoksam.features.avg_ticket:,}원" in client.summary_prompt


def test_summary_prompt_says_no_price_when_zero(yeoksam: Panel, shop, copy) -> None:
    """0 원은 '가격 없음'이다 — 가격 얘기를 꺼내지 말라고 알려준다."""
    brief = AdBrief(goal="copy", product="크로플", price=0)
    client = _suggest(_reply_by_demo(yeoksam), [])
    evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)
    assert "가격이 없다" in client.summary_prompt


def test_zero_price_ad_rejects_any_amount(yeoksam: Panel, shop, copy) -> None:
    brief = AdBrief(goal="copy", product="크로플", price=0)
    client = _suggest(_reply_by_demo(yeoksam), ["7,000원으로 낮춰보세요"])
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    # 지어낸 금액은 버려진다. 다만 제안이 통째로 비면 재생성이 죽으므로
    # 집계에서 뽑은 한 줄이 대신 들어간다.
    assert not any("7,000원" in s for s in result.suggestions)
    assert result.suggestions == _fallback_suggestions(result)


def test_summary_prompt_has_no_fabricated_example() -> None:
    """예시가 나쁜 행동을 가르친다 — 세로줄 사고와 같은 부류다.

    이전 "좋은 예"가 `'런치 세트 8,900원'` 이었고, 그 8,900원은 어디에도
    없는 금액이었다. 모델은 그 행동을 배웠다.
    """
    assert "8,900원" not in evaluator.SUMMARY_SYSTEM
    assert "숫자를 만들어내지 마라" in evaluator.SUMMARY_SYSTEM

    # 2026-08-13 아인님 실측: 제안 18개 중 8개가 아래 문장과 글자까지 같았다.
    # 그 문장이 이 프롬프트에 "쓸 수 있음" 예시와 JSON 예시로 두 번 박혀 있었다.
    # 8,900원 때와 같은 부류다 — 예시는 규칙이 아니라 본보기로 읽힌다.
    assert "세트 구성으로 묶어" not in evaluator.SUMMARY_SYSTEM
    assert "좋은 예" not in evaluator.SUMMARY_SYSTEM


def test_summary_cannot_turn_a_number_into_a_claim() -> None:
    """제안이 가격 분위를 품질 주장으로 옮겼다 (아인님 실측 2026-08-17).

        avg_ticket_pct 0.674  →  "서울 상위 33%의 품질을 자랑하는 크로플"

    숫자는 사실 블록에 있으니 `_quantities` 가드는 통과한다. 가드는 숫자가
    지어내진 것인지만 보고 **뜻이 바뀌었는지는 못 본다.** 그래서 규칙으로
    범위를 좁힌다 — 제안은 문구를 어떻게 쓸지에 대한 것이다.
    """
    assert "사장님만 할 수 있다" in evaluator.SUMMARY_SYSTEM
    assert "품질" in evaluator.SUMMARY_SYSTEM
    assert "쓸 수 있음" not in evaluator.SUMMARY_SYSTEM


def test_resistance_block_does_not_favour_one_label() -> None:
    """프롬프트가 가장 많이 말한 단어가 답이 된다.

    2026-08-13 아인님 실측: **금액이 한 글자도 없는 광고**에 12명 전원이
    걸림돌로 `price` 를 골랐다. 당시 걸림돌 블록에서 price 는 5회 언급되고
    목록 첫 자리였다 — 광고가 아니라 프롬프트를 고른 것이다.
    """
    block = evaluator.SYSTEM[evaluator.SYSTEM.index("**resistance**") :]
    block = block[: block.index("**evidence**")]

    counts = {
        "price": block.count("price") + block.count("값이 부담"),
        "message": block.count("message"),
        "relevance": block.count("relevance"),
        "none": block.count("none"),
    }
    assert counts["price"] <= min(counts["relevance"], counts["none"]), (
        f"price 가 다른 라벨보다 많이 언급된다: {counts}"
    )
    # 목록 첫 자리도 편향이다. 정직한 기본값(none)이 먼저 와야 한다.
    order = [lab for lab in ("none", "relevance", "message", "price") if lab in block]
    assert block.index("none") < block.index("price"), f"none 이 price 보다 뒤에 있다: {order}"


def test_none_is_reachable_at_any_score() -> None:
    """`none` 이 점수 문턱에 묶여 있으면 안 된다.

    이전 프롬프트: "`intent` 를 61 이상으로 줬다면 `none` 을 골라라".
    그런데 점수 기준표는 41~60 이 "괜찮네 정도"다. 대부분의 광고가 거기 들어가고,
    그러면 **손님은 반드시 흠을 하나 대야 했다.** `none` 은 광고가 훌륭할 때만
    열리는 문이었다 — 아인님이 관측한 "걸림돌 라벨이 입력에 반응하지 않는다"의
    구조적 원인이다.
    """
    assert "61 이상으로 줬다면" not in evaluator.SYSTEM
    assert "점수가 몇 점이든 상관없다" in evaluator.SYSTEM


def test_prompt_does_not_prime_price_while_forbidding_it() -> None:
    """가격을 막으려고 쓴 문장이 가격을 가르친다 — 세로줄·8,900원과 같은 부류."""
    assert "비슷하면 `price` 가 아니다" not in evaluator.SYSTEM


# --- 경계 계약 (2026-08-11 아인님이 화면에서 찾은 버그) -------------------------
#
# `AttributeError: 'ContrastNote' object has no attribute 'fit'`
#
# 아인님 테스트는 `Note` 를, 제 테스트는 `ContrastNote` 를 각각 직접 씁니다.
# 391개가 전부 초록불인데 **둘을 잇는 지점은 아무도 안 봤습니다.**
# 각자 테스트를 아무리 잘 짜도 경계는 비어 있습니다 — 그 경계를 여기서 봅니다.


def test_contrast_note_covers_every_note_field() -> None:
    """`Note` 에 필드가 늘면 `ContrastNote` 도 따라와야 한다.

    이게 없으면 아인님이 필드를 추가할 때마다 화면이 죽고, 그때까지
    양쪽 테스트는 모두 통과한다.
    """
    from app_core.panel.contrast import Note

    missing = set(Note._fields) - set(ContrastNote.model_fields)
    assert not missing, f"ContrastNote 에 없는 Note 필드: {missing}"


def test_conversion_carries_every_field(yeoksam: Panel, shop, brief, copy) -> None:
    """필드를 하나씩 적어 넘기는 구조라 빠뜨리기 쉽다 — 값까지 확인한다."""
    from app_core.panel.contrast import Note, contrast

    source = {n.kind: n for n in contrast(yeoksam.features, brief, copy)}
    result = evaluate(
        yeoksam, shop, brief, copy, client=FakeClient(_reply_by_demo(yeoksam)), consistency_k=1
    )

    assert source, "대조가 하나도 안 나오면 이 테스트가 아무것도 검사하지 않는다"
    for note in result.contrast_notes:
        origin = source[note.kind]
        for field in Note._fields:
            assert getattr(note, field) == getattr(origin, field), f"{note.kind}.{field}"


def test_screen_can_read_every_contrast_field(yeoksam: Panel, shop, brief, copy) -> None:
    """화면이 실제로 읽는 접근을 흉내 낸다 — 죽었던 지점이 여기다."""
    result = evaluate(
        yeoksam, shop, brief, copy, client=FakeClient(_reply_by_demo(yeoksam)), consistency_k=1
    )
    for note in result.contrast_notes:
        assert isinstance(note.kind, str)
        assert isinstance(note.text, str)
        assert note.fit is None or 0.0 <= note.fit <= 1.0


# --- 광고가 말한 시간대를 근거로 준다 (2026-08-11 실측에서 나온 것) -------------


def test_mentioned_slot_is_offered(yeoksam: Panel) -> None:
    """광고가 새벽을 말하면 새벽 수치를 줘야 근거로 인용할 수 있다.

    실측: "새벽 감성" 광고에 `time_share.00-06`(0.0007)을 받은 손님이 0명이라
    "이 동네는 새벽에 안 산다"를 숫자로 말할 방법이 없었다. 시간대 쌍 판별
    점수차가 +2.3 에 그쳤다 — 가격 쌍은 +25.5 였다.
    """
    persona = yeoksam.personas[0]
    dawn = CopyCandidate(headline="새벽 감성 크로플", sub="해 뜨기 전에 드세요")

    assert "time_share.00-06" in offered_paths(yeoksam.features, persona, dawn)
    assert "time_share.00-06" not in offered_paths(yeoksam.features, persona)


def test_mentioned_slot_reaches_every_persona(yeoksam: Panel) -> None:
    dawn = CopyCandidate(headline="새벽 감성 크로플")
    for persona in yeoksam.personas:
        assert "time_share.00-06" in offered_paths(yeoksam.features, persona, dawn)


def test_no_slot_mentioned_adds_nothing(yeoksam: Panel) -> None:
    """시점을 안 말한 광고에 엉뚱한 시간대를 끼워 넣으면 안 된다."""
    persona = yeoksam.personas[0]
    plain = CopyCandidate(headline="겉바속촉 크로플")

    assert offered_paths(yeoksam.features, persona, plain) == offered_paths(
        yeoksam.features, persona
    )


def test_prompt_and_gate_agree_on_the_mentioned_slot(yeoksam: Panel, shop, brief) -> None:
    """프롬프트에 준 것과 게이트가 인정하는 것이 같아야 한다."""
    persona = yeoksam.personas[0]
    dawn = CopyCandidate(headline="새벽 감성 크로플")

    block = evaluator._feature_lines(yeoksam.features, persona, dawn)
    in_prompt = {line.split(" = ")[0].removeprefix("- ") for line in block.splitlines()}
    assert in_prompt == offered_paths(yeoksam.features, persona, dawn)


def test_mentioned_slot_evidence_passes_the_gate(yeoksam: Panel, shop, brief) -> None:
    """새벽 수치를 근거로 든 응답이 통과해야 한다 — 주고서 막으면 안 된다."""
    dawn = CopyCandidate(headline="새벽 감성 크로플")
    by_demo = {p.demo: p for p in yeoksam.personas}

    def reply(persona_id: str, _calls: list[str]) -> dict[str, Any]:
        return _good(
            by_demo[persona_id],
            evidence=[{"path": "time_share.00-06", "value": 0.0007}],
        )

    result = evaluate(yeoksam, shop, brief, dawn, client=FakeClient(reply), consistency_k=1)
    assert result.excluded_cnt == 0


def test_time_words_are_shared_with_contrast() -> None:
    """목록을 복사해두면 대조와 평가가 서로 다른 시간대를 보게 된다."""
    from app_core.panel import contrast as C

    assert evaluator.TIME_WORDS is C.TIME_WORDS


# --- 손님별 위치를 평가에 전달 (2026-08-11 계측에서 나온 것) --------------------


def test_standing_distinguishes_core_from_missed(yeoksam: Panel) -> None:
    """실측: 손님 편차가 0.0 이었다 — 12명이 한 명도 빠짐없이 같은 점수를 냈다.

    "12명 패널"이 사실상 1명이었다는 뜻이다. 12명이 받는 정보 중 실제로 다른
    것은 나이·성별과 이 위치뿐이라, 위치를 문장으로 준다.
    """
    core = next(p for p in yeoksam.personas if p.demo.startswith("30"))
    missed = next(p for p in yeoksam.personas if p.demo.startswith("10"))

    assert "핵심 고객" in evaluator.standing(yeoksam.features, core)
    assert "놓치고 있는 층" in evaluator.standing(yeoksam.features, missed)


def test_standing_actually_splits_the_panel(yeoksam: Panel) -> None:
    """전원 같은 문장을 받으면 넣으나 마나다 — 실제로 갈리는지 본다."""
    said = {evaluator.standing(yeoksam.features, p) for p in yeoksam.personas}
    assert len(said) >= 3, "12명이 최소 세 갈래로는 나뉘어야 한다"


def test_standing_reaches_the_prompt(yeoksam: Panel, shop, brief, copy) -> None:
    core = next(p for p in yeoksam.personas if p.demo.startswith("30"))
    missed = next(p for p in yeoksam.personas if p.demo.startswith("10"))

    assert "핵심 고객" in build_user_prompt(core, yeoksam.features, shop, brief, copy)
    assert "놓치고 있는 층" in build_user_prompt(missed, yeoksam.features, shop, brief, copy)


def test_standing_handles_missing_backyard(yeoksam: Panel) -> None:
    """발달상권은 배후지가 없다 — `None` 매핑에서 터지면 안 된다."""
    assert yeoksam.features.back_age_share is None
    for persona in yeoksam.personas:
        assert evaluator.standing(yeoksam.features, persona)


def test_standing_thresholds_match_the_narrator(yeoksam: Panel) -> None:
    """서사와 평가가 다른 기준으로 같은 손님을 설명하면 모델이 헷갈린다."""
    from app_core.panel import narrator

    source = inspect.getsource(narrator._pool_ratio)
    assert "1.15" in source and str(evaluator._POOL_HIGH) == "1.15"
    assert "0.85" in source and str(evaluator._POOL_LOW) == "0.85"


def test_resistance_prompt_ties_to_the_persona() -> None:
    """실측: 걸림돌이 좋은 광고에서도 전원 price 였다 — 정보가 0 이다."""
    assert "네 처지에서 고른다" in evaluator.SYSTEM
    assert "억지로 찾지 마라" in evaluator.SYSTEM


def test_resistance_is_tied_to_the_persona_own_intent() -> None:
    """걸림돌을 점수에 묶었더니 `none` 이 도달 불가능해졌다 — 되돌린다.

    2026-08-13 아인님 실측이 뒤집은 부분이다. 금액이 한 글자도 없는 광고에도
    12/12 가 price 를 골랐다. 원인은 이 프롬프트 안에서 두 규칙이 부딪힌 것이다.

        점수 기준표   41~60 = "괜찮네 정도"
        걸림돌 규칙   intent 61 이상이면 none

    광고 대부분이 "괜찮네 정도"에 들어가므로 **손님은 반드시 흠을 하나 대야
    했다.** `none` 은 광고가 훌륭할 때만 열리는 문이었다. 그래서 문턱을 걷어내고
    걸림돌을 점수에서 떼어낸다.
    """
    assert "61 이상으로 줬다면 `none`" not in evaluator.SYSTEM
    assert "점수가 몇 점이든 상관없다" in evaluator.SYSTEM

    # 가격을 막으려고 쓴 문장이 가격을 가르쳤다. 이 블록에서 price 만 5회
    # 언급되고 목록 첫 자리였다 — 세로줄·8,900원과 같은 부류다.
    assert "avg_ticket` 과 견줘봐라" not in evaluator.SYSTEM
    block = evaluator.SYSTEM.split("**resistance**")[1].split("**evidence**")[0]
    assert block.index("none") < block.index("price")
    assert block.count("price") <= block.count("none")


# --- 재생성 연결부 (2026-08-14) ---------------------------------------------


def test_suggestions_never_empty(yeoksam: Panel, shop, brief, copy) -> None:
    """제안이 비면 다시 만들기가 통째로 죽는다.

    재생성 입력인 `schema.Feedback.notes` 가 `min_length=1` 이다(건오님).
    요약 콜은 실패할 수 있는 부가물인데, 그 실패가 재생성까지 끌고 가면 안 된다.
    """
    from app_core.schema import Feedback

    client = FakeClient(_reply_by_demo(yeoksam))
    result = evaluate(yeoksam, shop, brief, copy, client=client, summarize=False)

    assert result.suggestions
    # 실제 소비 지점을 그대로 태워 본다 — 여기서 터지면 화면에서도 터진다.
    Feedback(source="panel", notes=result.suggestions, resistance=result.top_resistance)


def test_fallback_note_names_the_weakest_metric() -> None:
    """지어낸 말이 아니라 집계된 점수에서 가장 약한 지표를 짚어야 한다."""
    result = EvaluationResult(
        ad_id="ad-001",
        scores={"attention": 71.0, "message": 40.0, "intent": 63.0},
        confidence="ok",
        max_metric_std=0.0,
        top_resistance=[],
        persona_comments=[],
        area_nm="역삼역",
        quarter="20261",
        is_fallback=False,
        demo_coverage=0.714,
    )
    (note,) = _fallback_suggestions(result)
    assert "무엇을 파는 곳인지" in note
    assert "40점" in note


def test_summary_sees_more_than_price(yeoksam: Panel, shop, brief, copy) -> None:
    """요약 콜이 볼 수 있는 사실이 가격 두 줄뿐이었다 (아인님 실측 2026-08-13).

    제안 18개 중 가격 12개, 시점 0개. 바로 7줄 위에서 만든 대조 문장을
    안 넘기고 있었다 — 근거 A등급이고 LLM 도 안 쓰는데 버려지고 있었다.
    """
    seen: list[str] = []

    class Spy(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님들의 평가를"):
                seen.append(user)
            return super().complete_json(system, user)

    evaluate(yeoksam, shop, brief, copy, client=Spy(_reply_by_demo(yeoksam)))

    assert seen, "요약 콜이 안 갔다"
    facts = seen[0].split("## 손님 반응")[0]
    non_price = [ln for ln in facts.splitlines() if ln.startswith("- ") and "원" not in ln]
    assert non_price, f"사실이 여전히 가격뿐이다:\n{facts}"


# --- 걸림돌이 가격으로 쏠리던 구조 (2026-08-14) ------------------------------


def test_price_numbers_hidden_when_ad_has_no_price(yeoksam: Panel, shop, copy) -> None:
    """가격 없는 광고에는 객단가를 보여주지 않는다.

    아인님 실측(2026-08-13): **금액이 한 글자도 없는 광고**에 12/12 가 걸림돌로
    price 를 골랐다. 근거는 '우리 동네 숫자'에서만 인용할 수 있는데 그 공통
    4개 중 2개가 가격이었다. 견줄 가격이 없으면 객단가는 광고 평가와 무관하다.
    """
    persona = yeoksam.personas[0]
    with_price = offered_paths(yeoksam.features, persona, copy, show_price=True)
    without = offered_paths(yeoksam.features, persona, copy, show_price=False)

    assert {"avg_ticket", "avg_ticket_pct"} <= with_price
    assert not ({"avg_ticket", "avg_ticket_pct"} & without)
    # 뺀 만큼 다른 동네 신호는 남아 있어야 한다 — 댈 것이 없으면 또 지어낸다.
    assert {"competitor_cnt", "open_cnt", "close_cnt"} <= without


def test_common_numbers_are_not_price_dominated(yeoksam: Panel, shop, copy) -> None:
    """공통 숫자가 가격 쪽으로 쏠려 있으면 손님이 댈 이야기도 가격뿐이 된다."""
    persona = yeoksam.personas[0]
    common = offered_paths(yeoksam.features, persona, copy) - {ref.path for ref in persona.evidence}
    price_ish = {p for p in common if "ticket" in p}
    assert len(price_ish) * 2 <= len(common), f"공통 {len(common)}개 중 가격 {price_ish}"


def test_price_sense_is_a_person_not_a_neighbourhood(yeoksam: Panel, shop, brief, copy) -> None:
    """가격 감각은 손님의 성격이지 동네의 성격이 아니다.

    옛 문장은 `narrator.PRICE_KO` 와 이어져 `"가격에 민감한 동네에 산다"` 가
    됐다. 바로 앞 둘은 사람 이야기인데(`"점심에 주로 움직이고"`,
    `"늘 가던 곳을 다시 찾는 편"`) 가격만 주어가 동네로 바뀌어 있었다.

    나는 이 줄을 통째로 뺐었는데, 아인님이 사람 문장으로 바꿔 재보니 싼 광고에서
    걸림돌 price 가 8/12 → 4/12 로 줄었다(2026-08-14). 손님을 가르는 축 하나를
    통째로 버릴 이유가 없어 되살렸다.
    """
    text = build_user_prompt(yeoksam.personas[0], yeoksam.features, shop, brief, copy)

    assert "동네에 산다" not in text
    assert "가격에 민감한" not in text
    assert "가격 저항이 낮은" not in text
    assert evaluator._PRICE_SENS_KO[yeoksam.personas[0].axes.price_sens] in text


def test_every_price_sense_has_a_person_phrase() -> None:
    """축 값이 늘면 KeyError 로 죽는다 — 빠짐없이 갖고 있어야 한다."""
    from app_core.panel.schemas import PriceSens

    assert set(evaluator._PRICE_SENS_KO) == set(get_args(PriceSens))
    for phrase in evaluator._PRICE_SENS_KO.values():
        assert phrase.endswith("편이다.")


def test_price_resistance_is_challenged_when_ad_has_no_price(yeoksam: Panel, shop, copy) -> None:
    """가격 없는 광고에 price 라고 답하면 한 번 되묻는다.

    코드가 아는 사실이므로 모델의 자기검열에 맡기지 않는다.
    """
    brief = AdBrief(goal="copy", product="크로플", price=0)
    seen: list[str] = []

    class Stubborn(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system is evaluator.SYSTEM or system.startswith("너는 아래 특성"):
                seen.append(user)
            return super().complete_json(system, user)

    client = Stubborn(_reply_by_demo(yeoksam, resistance="price"))
    evaluator.evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert any("가격이 적혀 있지 않다" in u for u in seen), "되묻지 않았다"


# --- 걸림돌 목록에 빠진 칸 (2026-08-14 실측) --------------------------------


def test_alternative_resistance_exists() -> None:
    """ "다른 데가 있다"를 담을 라벨이 없어서 price 로 몰렸다.

    실측(3,000원 아메리카노 · 동네 결제 평균 9,546원): 12명 전원이 `price`
    를 골랐는데 코멘트는 하나같이 가격이 괜찮다고 말했다. 진짜 이유는
    "다른 카페와 비교"(5명) · "자주 가던 곳이 있어서"(4명) 였다.

    무엇보다 이건 우리가 만든 상황이다 — 프롬프트가 12명 전원에게
    `motive=habitual`("늘 가던 곳을 다시 찾는 편")이라고 말해 놓고,
    무엇이 걸리냐 물으면서 그 답을 주지 않았다.
    """
    from app_core.panel.schemas import Resistance

    assert "alternative" in get_args(Resistance)
    assert "alternative" in evaluator.SYSTEM
    assert "늘 가던 데가 있다" in evaluator.SYSTEM


def test_retry_hint_lists_every_allowed_label() -> None:
    """힌트가 라벨 하나를 빠뜨리면 모델이 그 답을 다시 안 쓴다.

    세로줄 사고(2026-08-07)와 같은 자리다 — 교정 지시가 곧 본보기가 된다.
    """
    from app_core.panel.schemas import Resistance

    hint = evaluator._retry_hint("JSON 형식이나 값이 스키마에 맞지 않았다.")
    del hint  # 힌트 본문은 _evaluate_one 안에서 조립된다
    src = inspect.getsource(evaluator._evaluate_one)
    for label in get_args(Resistance):
        if label == "visual":
            continue  # 광고 이미지를 안 보므로 애초에 못 고른다
        assert label in src, f"재시도 힌트에 {label} 이 빠졌다"


# --- 걸림돌은 코멘트가 정한다 (2026-08-14 실측 5회) --------------------------


def test_resistance_comes_from_the_comment_not_the_persona_call(
    yeoksam: Panel, shop, brief, copy
) -> None:
    """손님이 고른 라벨을 코멘트 분류가 덮어쓴다.

    실측: 인용할 수 있는 숫자가 라벨을 정하고 있었다.

        avg_ticket 안 보여줌  →  price  0/12
        avg_ticket 보여줌     →  price 12/12   (라벨을 늘려도 그대로)

    코멘트에는 진짜 이유가 적혀 있었다 — 12명이 "늘 가던 곳이 있어서"라고
    써놓고 라벨은 price 를 골랐다. 그래서 분류를 떼어냈다.
    """
    n = len(yeoksam.personas)
    client = FakeClient(_reply_by_demo(yeoksam, resistance="price"), labels=["alternative"] * n)
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert {c.resistance for c in result.persona_comments} == {"alternative"}
    assert result.top_resistance == ["alternative"]


def test_resistance_classifier_sees_only_comments(yeoksam: Panel, shop, brief, copy) -> None:
    """분류 콜에 숫자나 근거 목록이 새어 들어가면 오염이 되돌아온다."""
    seen: list[str] = []

    class Spy(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                seen.append(user)
            return super().complete_json(system, user)

    evaluate(yeoksam, shop, brief, copy, client=Spy(_reply_by_demo(yeoksam)), consistency_k=1)

    assert seen, "걸림돌 분류 콜이 안 갔다"
    payload = seen[0]
    assert "avg_ticket" not in payload
    assert "우리 동네 숫자" not in payload
    assert str(yeoksam.features.avg_ticket) not in payload


def test_bad_classifier_response_keeps_original_labels(yeoksam: Panel, shop, brief, copy) -> None:
    """분류가 헛소리를 하면 손님이 고른 라벨을 그대로 쓴다.

    부가 콜 하나 때문에 이미 끝난 12명의 평가를 버리지 않는다.
    """

    class Broken(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                return {"labels": {"1": "없는라벨"}}
            return super().complete_json(system, user)

    result = evaluate(
        yeoksam,
        shop,
        brief,
        copy,
        client=Broken(_reply_by_demo(yeoksam, resistance="message")),
        consistency_k=1,
    )
    assert {c.resistance for c in result.persona_comments} == {"message"}


def test_classifier_failure_does_not_void_scores(yeoksam: Panel, shop, brief, copy) -> None:
    """분류 콜이 터져도 점수는 살아 있어야 한다."""

    class Boom(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                raise RuntimeError("분류 실패")
            return super().complete_json(system, user)

    result = evaluate(
        yeoksam, shop, brief, copy, client=Boom(_reply_by_demo(yeoksam)), consistency_k=1
    )
    assert result.scores
    assert len(result.persona_comments) == len(yeoksam.personas)


def test_classifier_prompt_warns_about_praised_price() -> None:
    """실측에서 12/12 가 "가격은 괜찮지만" 이라 쓰고 price 를 골랐다."""
    assert "괜찮다" in evaluator.RESISTANCE_SYSTEM
    assert "그렇지만" in evaluator.RESISTANCE_SYSTEM
    for label in get_args(Resistance):
        if label == "visual":
            continue
        assert label in evaluator.RESISTANCE_SYSTEM


def test_follow_up_calls_are_budgeted(yeoksam: Panel, shop, brief, copy) -> None:
    """뒤따르는 콜을 예산에서 안 빼면 자기일관성이 상한을 넘긴다.

    2026-08-14 에 걸림돌 분류 콜을 넣으면서 실제로 21콜이 나갔다 (상한 20).
    `FOLLOW_UP_CALLS` 로 묶어 두었으니 콜이 또 늘어도 여기서 잡힌다.
    """
    client = FakeClient(_reply_by_demo(yeoksam))
    evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=3)

    assert len(client.calls) <= MAX_EVAL_CALLS
    assert client.calls.count("summary") + client.calls.count("resistance") == FOLLOW_UP_CALLS


def test_every_system_prompt_says_json() -> None:
    """`complete_json` 은 응답을 JSON 으로 강제한다 — 그 조건이 프롬프트에 있다.

    OpenAI 의 `response_format={"type": "json_object"}` 는 메시지 어딘가에
    **"json" 이라는 단어가 있어야** 요청을 받아준다. 없으면 400 이다.

    2026-08-14 실측에서 걸림돌 분류 콜이 통째로 실패했는데, 원인이 이것이었다.
    `{"labels": [...]}` 를 적어 두었으니 JSON 인 게 분명하다고 생각했지만
    API 는 글자 그대로 "json" 을 찾는다. 폴백이 잘 작동해서 결과가 조용히
    옛 라벨로 돌아갔고, 로그를 안 봤으면 "고쳐도 안 바뀐다"고 오판했을 것이다.

    프롬프트가 늘 때마다 반복될 함정이라 전수로 검사한다.
    """
    prompts = {
        name: value
        for name, value in vars(evaluator).items()
        if name.isupper() and name.endswith("SYSTEM") and isinstance(value, str)
    }
    assert prompts, "검사할 시스템 프롬프트를 못 찾았다"
    for name, text in prompts.items():
        assert "json" in text.lower(), f"{name} 에 'json' 이라는 단어가 없다"


def test_classifier_tolerates_extra_and_missing_numbers(yeoksam: Panel, shop, brief, copy) -> None:
    """번호가 하나 더 오거나 빠져도 어긋난 자리만 버린다.

    2026-08-14 실측: 12명을 물었는데 라벨 13개가 왔다. 목록으로 받아 자리로
    맞추면 하나만 밀려도 12명이 통째로 뒤섞이므로, 번호를 열쇠로 받는다.
    옛 구현은 개수가 안 맞으면 **전부** 버려서 멀쩡한 11명분도 날아갔다.
    """
    n = len(yeoksam.personas)

    class Sloppy(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                labels = {str(i + 1): "alternative" for i in range(n)}
                labels.pop("2")  # 하나 빠뜨리고
                labels[str(n + 1)] = "none"  # 없는 번호를 더한다
                return {"labels": labels}
            return super().complete_json(system, user)

    result = evaluate(
        yeoksam,
        shop,
        brief,
        copy,
        client=Sloppy(_reply_by_demo(yeoksam, resistance="price")),
        consistency_k=1,
    )
    by_id = {c.persona_id: c.resistance for c in result.persona_comments}
    assert sum(v == "alternative" for v in by_id.values()) == n - 1
    assert sum(v == "price" for v in by_id.values()) == 1  # 빠진 자리는 원래 라벨


def test_classifier_input_has_no_line_breaks(yeoksam: Panel, shop, brief, copy) -> None:
    """코멘트에 줄바꿈이 있으면 모델이 항목을 더 세어 번호가 어긋난다."""
    seen: list[str] = []
    by_demo = {p.demo: p for p in yeoksam.personas}

    def reply(demo: str, _calls: list[str]) -> dict[str, Any]:
        return _good(by_demo[demo], comment="첫 줄이다\n둘째 줄이다")

    class Spy(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                seen.append(user)
            return super().complete_json(system, user)

    evaluate(yeoksam, shop, brief, copy, client=Spy(reply), consistency_k=1)

    assert seen
    assert len(seen[0].splitlines()) == len(yeoksam.personas)


def test_classifier_cannot_pick_price_without_a_price(yeoksam: Panel, shop, copy) -> None:
    """분류에도 같은 규칙을 건다 — 적히지도 않은 가격은 걸림돌이 못 된다.

    2026-08-14 회귀: 손님 콜만 막아 두었더니 분류가 "가격이 궁금해서"를
    price 로 읽어 그대로 샜다. 코드가 아는 사실은 양쪽 콜에 다 걸어야 한다.
    """
    brief = AdBrief(goal="copy", product="크로플", price=0)
    n = len(yeoksam.personas)

    class SaysPrice(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                assert "가격이 적혀 있지 않다" in system, "분류 콜에 규칙이 안 갔다"
                return {"labels": {str(i + 1): "price" for i in range(n)}}
            return super().complete_json(system, user)

    result = evaluate(
        yeoksam,
        shop,
        brief,
        copy,
        client=SaysPrice(_reply_by_demo(yeoksam, resistance="message")),
        consistency_k=1,
    )
    assert "price" not in {c.resistance for c in result.persona_comments}
    assert "price" not in result.top_resistance


def test_classifier_rule_is_not_added_when_price_exists(yeoksam: Panel, shop, brief, copy) -> None:
    """가격이 있는 광고에는 그 규칙을 붙이지 않는다 — 붙이면 price 를 못 고른다.

    ⚠️ **문구에 금액이 실려 있어야 한다.** 2026-08-20 부터 "가격이 있는 광고"는
    사장님이 입력했는지가 아니라 **광고에 보이는지**로 정한다 (`contrast.price_visible`).
    입력만 하고 문구에 안 실리면 손님은 그 값을 모르므로 가격 축을 닫는다.
    """
    seen: list[str] = []

    class Spy(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                seen.append(system)
            return super().complete_json(system, user)

    priced = CopyCandidate(headline=f"크로플 {brief.price:,}원", sub=copy.sub)
    evaluate(yeoksam, shop, brief, priced, client=Spy(_reply_by_demo(yeoksam)), consistency_k=1)

    assert seen and "가격이 적혀 있지 않다" not in seen[0]


def test_가격이_문구에_없으면_여섯_자리가_모두_닫힌다(yeoksam: Panel, shop, brief, copy) -> None:
    """가격 축을 읽는 자리가 여섯이다. **하나만 빠뜨려도 어긋난다.**

    손님에게는 가격을 안 보여주는데 분류는 price 를 고를 수 있는 상태가 되면
    2026-08-20 에 잡은 문제가 그대로 남는다. 그래서 여섯 자리가 같은 판정
    (`contrast.price_visible`)을 보는지 한 번에 확인한다.

    `brief` 는 가격 9,500원이고 `copy` 에는 금액이 없다 — 지금 생성되는 문구
    대부분이 이 상태다 (실측 2026-08-12: 문구 27개 중 3건이 금액 누락).
    """
    seen: dict[str, str] = {}

    class Spy(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님이 남긴 한 줄을"):
                seen["classify"] = system
            elif system.startswith("손님들의 평가를"):
                seen["summary"] = user
            else:
                seen.setdefault("persona", user)
            return super().complete_json(system, user)

    result = evaluate(
        yeoksam, shop, brief, copy, client=Spy(_reply_by_demo(yeoksam)), consistency_k=1
    )

    # ① 손님 프롬프트의 가격 줄 · ② 손님에게 보여주는 숫자 목록
    assert "- 가격: 광고에 없음" in seen["persona"]
    assert "avg_ticket" not in seen["persona"]
    # ③ 근거 경로 — 객단가를 인용할 수 없다
    assert "avg_ticket" not in str(
        offered_paths(
            yeoksam.features, yeoksam.personas[0], copy, show_price=price_visible(brief, copy)
        )
    )
    # ④ 분류 콜에 "가격이 적혀 있지 않다" 가 붙는다
    assert "가격이 적혀 있지 않다" in seen["classify"]
    # ⑤ 요약 콜의 사실 블록
    assert "광고에 가격이 없다" in seen["summary"]
    assert f"{brief.price:,}원" not in seen["summary"]
    # ⑥ 되묻기가 걸린 뒤에도 평가는 끝난다
    assert result.scores


def test_대체_문장은_인원을_실제로_센다() -> None:
    """패널은 10~12명 가변이다(#39) — 무작위 60조합에서 3명짜리도 나왔다.

    제안 문장의 "12명" 은 #40 이 고쳤는데 대체 문장에는 남아 있었다.
    요약 콜이 실패한 날 3명 패널에 "손님 12명" 이라고 말하게 된다.
    """
    from app_core.panel.evaluator import _fallback_suggestions

    result = EvaluationResult(
        ad_id="x",
        scores={"attention": 40.0, "message": 70.0, "intent": 60.0},
        confidence="low",
        max_metric_std=0.0,
        top_resistance=[],
        persona_comments=[
            PersonaComment(
                persona_id=f"p{i}",
                demo="30대 여성",
                weight=0.33,
                is_boundary=False,
                resistance="none",
                comment="한마디",
            )
            for i in range(3)
        ],
        area_nm="역삼역",
        quarter="20261",
        is_fallback=False,
        demo_coverage=0.714,
    )
    (note,) = _fallback_suggestions(result)
    assert "손님 3명" in note
    assert "12명" not in note
    assert note.endswith("어떨까요 (손님 3명 가중평균 40점)")  # 권유형


def test_every_label_has_a_classifier_example() -> None:
    """예시가 없는 라벨은 안 나온다 — 예시 목록이 곧 답의 분포다.

    2026-08-18 아인님 실측: `relevance` 만 예시가 없었고, 나와야 할 자리
    (10대 타깃 광고 · 역삼 직장인 93.6%)에서 0건이었다. 예시 한 줄을 넣자
    `alternative 7→0` · `relevance 1→8` 로 뒤집혔다.

    같은 병을 네 번째 만났다 — 세로줄(8/07) · 8,900원(8/11) · 제안 반복(8/13)
    은 "예시가 있어서" 였고 이번은 "없어서" 다. 기전은 하나다.
    라벨을 늘리면 예시도 같이 늘려야 한다. 그래서 코드에서 유도해 검사한다.
    """
    from app_core.panel.schemas import Resistance

    body = evaluator.RESISTANCE_SYSTEM
    exampled = {line.rsplit("→", 1)[1].strip() for line in body.splitlines() if "→" in line}
    selectable = {lab for lab in get_args(Resistance) if lab != "visual"}
    assert selectable <= exampled, f"예시 없는 라벨: {selectable - exampled}"


def test_summary_facts_carry_fit(yeoksam: Panel, shop, brief, copy) -> None:
    """대조 문장의 적합도(fit)가 요약 콜까지 넘어간다.

    문장만 주면 모델이 방향을 못 잡는다 — 실측(아인님 2026-08-18): 시점
    제안 7/18 이 전부 광고가 이미 말한 시간대를 *강조*하라고 했다. 매출이
    몰리는 쪽으로 *옮기라*는 판단은 fit 에만 있었다.
    """
    seen: list[str] = []

    class Spy(FakeClient):
        def complete_json(self, system: str, user: str) -> dict[str, Any]:
            if system.startswith("손님들의 평가를"):
                seen.append(user)
            return super().complete_json(system, user)

    evaluate(yeoksam, shop, brief, copy, client=Spy(_reply_by_demo(yeoksam)), consistency_k=1)

    assert seen, "요약 콜이 안 갔다"
    facts = seen[0].split("## 손님 반응")[0]
    assert "적합도" in facts, "fit 이 사실 블록에 없다"


def test_classifier_relevance_example_is_the_measured_one() -> None:
    """relevance 예시는 아인님이 실측한 그 문장이어야 한다.

    내가 지어낸 문장("10대 취향 같아서…")을 넣었다가 교체했다 — 아인님
    문장은 효과가 측정됐고(alternative 7→0, relevance 1→8) 내 것은 아니다.
    예시 문장 하나가 분포를 뒤집는 것을 다섯 번 봤으면, 예시는 측정된
    것만 쓴다.
    """
    assert "직장인이라 해당이 없네요" in evaluator.RESISTANCE_SYSTEM


# --- 근거 없는 상품 주장 (2026-08-19 아인님 실측, 두 번 샜다) ------------------


def test_price_percentile_cannot_become_a_quality_claim(yeoksam: Panel, shop, brief, copy) -> None:
    """가격 분위를 상품 자랑으로 옮겨 붙인 제안은 버린다.

    실측 두 건 — 숫자는 사실 블록에 있으니 `_quantities` 가드를 통과한다.
    바뀐 것은 **뜻**이고, 그건 그 가드가 못 본다.

        "서울 한식업종 상위 43%의 품질을 자랑하는 제육볶음 정식"
        "광고 문구에 '서울 상위 2%'의 품질을 강조하여..."

    `avg_ticket_pct` 는 그 동네 **가격**이 서울에서 몇 번째인가다. 상품
    품질과 무관하고, 사장님이 말한 적 없으니 광고로 나가면 허위다.
    """
    client = _suggest(
        _reply_by_demo(yeoksam),
        ["서울 상위 33%의 품질을 자랑하는 크로플로 문구를 바꿔보세요"],
    )
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert not any("품질" in s for s in result.suggestions)


def test_owner_own_words_are_allowed(yeoksam: Panel, shop, copy) -> None:
    """사장님이 직접 말한 자랑은 통과한다 — 그건 사장님의 주장이다."""
    brief = AdBrief(goal="copy", product="크로플", price=6000, extra="최고급 버터만 씁니다")
    client = _suggest(
        _reply_by_demo(yeoksam),
        ["사장님이 말씀하신 최고급 버터를 문구 앞에 드러내 보세요"],
    )
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert any("최고급" in s for s in result.suggestions)


def test_claim_guard_is_narrow(yeoksam: Panel, shop, brief, copy) -> None:
    """멀쩡한 제안을 버리면 안 된다 — 놓치는 쪽으로 기울여 뒀다."""
    ok = "점심 시간대를 문구 앞에 드러내 보세요"
    client = _suggest(_reply_by_demo(yeoksam), [ok])
    result = evaluate(yeoksam, shop, brief, copy, client=client, consistency_k=1)

    assert ok in result.suggestions


def test_claim_words_cover_the_measured_cases() -> None:
    """실측에 나온 낱말이 목록에 있어야 한다. 늘릴 때는 실측으로."""
    for word in ("품질", "자랑하는", "손꼽히는"):
        assert word in evaluator._CLAIM_WORDS


def _result_with(n: int) -> EvaluationResult:
    return EvaluationResult(
        ad_id="x",
        scores={"attention": 40.0, "message": 70.0, "intent": 60.0},
        confidence="low",
        max_metric_std=0.0,
        top_resistance=[],
        persona_comments=[
            PersonaComment(
                persona_id=f"p{i}",
                demo="30대 여성",
                weight=1.0 / n,
                is_boundary=False,
                resistance="none",
                comment="한마디",
            )
            for i in range(n)
        ],
        area_nm="역삼역",
        quarter="20261",
        is_fallback=False,
        demo_coverage=0.714,
    )


def test_두_명_이하는_가중평균이라_부르지_않는다() -> None:
    """**한 명의 평균은 평균이 아니다.**

    수호님이 씨앗 5개 300조합에서 손님 1명짜리 패널을 찾았다
    (한국의류시험연구원 × 옷가게 · 50대 남성 하나). `demo_coverage` 가
    1.000 이라 데이터가 부실한 게 아니라, 그 동네에서 옷을 사는 사람이
    정말 그 층뿐이었다.

    경계 3 은 `#56` 의 "손님 2명 이하는 가중평균이라 부를 수 없는 크기" 와
    같은 값이다.
    """
    from app_core.panel.evaluator import _fallback_suggestions

    for n in (1, 2):
        (note,) = _fallback_suggestions(_result_with(n))
        assert f"손님 {n}명 점수" in note, note
        assert "가중평균" not in note

    for n in (3, 12):
        (note,) = _fallback_suggestions(_result_with(n))
        assert f"손님 {n}명 가중평균" in note, note


def test_금액_가드가_한글_단위를_읽는다() -> None:
    r"""`_amounts` 는 제안이 **지어낸 금액**을 잡는 가드다.

    옛 규칙 `r"(\d[\d,]*)\s*원"` 은 한글 단위를 못 읽었다. 특히 두 번째가
    위험하다 — 23,500원을 500원으로 읽으면 "사실 블록에 있는 값"으로
    오판해 지어낸 금액이 그대로 사장님께 나간다.

        "1만 5천원"      옛 set()   → 새 {15000}
        "2만 3천 500원"  옛 {500}   → 새 {23500}
    """
    from app_core.panel.evaluator import _amounts

    assert _amounts("1만 5천원에 맞춰보세요") == {15000}
    assert _amounts("2만 3천 500원 세트를 만들어보세요") == {23500}
    assert _amounts("15,000원") == {15000}
    assert _amounts("원두를 바꿔보세요") == set()  # 숫자 없는 `원`


def test_금액_규칙이_contrast_와_같다() -> None:
    """규칙을 두 곳에 두면 한쪽만 고쳐진다 — PR #50 에서 겪은 그대로다."""
    from app_core.panel.contrast import copy_amounts
    from app_core.panel.evaluator import _amounts

    for text in ("1만 5천원", "2만 3천 500원", "4,500원", "원두", "9천원"):
        assert _amounts(text) == copy_amounts(CopyCandidate(headline=text)), text


def test_관문이_가격_평가어를_잡는다() -> None:
    """관문이 재료·품질만 막아서 **가격 주장은 통과했다** (실측 2026-08-21).

        "평양냉면 가격을 '합리적인 가격'으로 강조하여 부담감을 줄여보세요"
        "'가성비 좋은 평양냉면'이라는 문구를 추가하여…"
        "연어덮밥의 가격을 '합리적인 가격'으로 강조하는 문구를 추가해 보세요"

    18,000원을 '합리적'이라고 부르는 것도 사장님이 말한 적 없는 사실 주장이다.
    """
    from app_core.panel.evaluator import _unbacked_claims

    assert _unbacked_claims("'합리적인 가격'으로 강조해보세요", "") == {"합리적"}
    assert _unbacked_claims("'가성비 좋은 평양냉면'을 추가하여", "") == {"가성비"}


def test_사장님이_한_말이면_가격어도_통과한다() -> None:
    """`backing` 은 사장님이 실제로 한 말이다. 사장님의 주장은 막지 않는다."""
    from app_core.panel.evaluator import _unbacked_claims

    assert (
        _unbacked_claims("'합리적인 가격'으로 강조해보세요", "합리적인 가격으로 알리고 싶다")
        == set()
    )


def test_멀쩡한_제안은_그대로_통과한다() -> None:
    """이 관문은 '놓치는 쪽으로 기울여' 두는 것이 원칙이다 — 좁게 유지한다."""
    from app_core.panel.evaluator import _unbacked_claims

    assert _unbacked_claims("지금 가야 할 이유를 한 줄 넣어보시면 어떨까요", "") == set()
    assert _unbacked_claims("영업시간을 광고에 적어보시면 어떨까요", "") == set()
