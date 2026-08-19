"""프롬프트 판별기 테스트 — 회귀 코퍼스는 전부 실제 사고 문자열이다.

지어낸 문장으로 검증하면 판별기가 실전에서 어떻게 틀리는지 알 수 없다
(price_contradictions 첫 판이 그렇게 5/5 오탐을 냈다). 그래서 다섯 번의
사고에서 실제로 문제였던 문자열을 그대로 박아 둔다 — 검사를 고치다
옛 사고를 다시 통과시키면 여기서 걸린다.
"""

from __future__ import annotations

from typing import get_args

import pytest
from prompt_lint import (
    amount_in_example,
    copyable_free_text,
    json_keyword,
    label_bias,
    missing_label_example,
    pipe_placeholder,
    score_tied_label_rule,
)

from app_core.panel import evaluator
from app_core.panel.schemas import Resistance

SELECTABLE = tuple(lab for lab in get_args(Resistance) if lab != "visual")


# --- 회귀 코퍼스: 실제 사고가 걸리는가 --------------------------------------


def test_incident_0807_pipe_placeholder() -> None:
    """세로줄 예시 — 21/23 콜이 그대로 베껴 스키마에서 탈락했다."""
    old = '"resistance": "price|message|relevance|none"'
    assert pipe_placeholder(old)
    assert not pipe_placeholder('"resistance": "price"')


def test_incident_0811_amount_in_example() -> None:
    """'런치 세트 8,900원' — 어디에도 없는 금액이 답에 다시 나타났다."""
    old = '  좋은 예: "런치 세트 8,900원, 오늘도 10분 컷"'
    assert amount_in_example(old)
    # 규칙 본문의 금액 언급은 예시가 아니다 — 잡으면 오탐이다.
    assert not amount_in_example("가격은 사장님이 정하는 값이다. 9,546원과 견주지 마라.")


def test_incident_0813_copyable_suggestion() -> None:
    """제안 18개 중 8개가 예시 문장과 글자까지 같았다.

    사고 원문은 `{"suggestions": ["가격을 낮추기보다 세트 구성으로..."]}` 인데
    리스트 값이라 `_JSON_STR_VALUE` 꼴이 아니다 — 같은 부류였던
    `comment` 예시(이것도 그대로 복사됐다)로 재현한다.
    """
    old_kv = '"comment": "맛은 궁금한데 가격에서 손이 멈추네요."'
    assert copyable_free_text(old_kv)
    assert not copyable_free_text('"comment": "<한 문장. 무엇이 끌렸고 무엇이 걸렸는지>"')


def test_incident_0814_label_bias() -> None:
    """price 5회 언급 + 목록 첫 자리 → 금액 없는 광고에 12/12 price."""
    old = (
        "  price      가격이 부담되거나 값어치를 모르겠다\n"
        "  message    무슨 말인지 모르겠거나 와닿지 않는다\n"
        "  relevance  나와 상관없는 광고로 느껴진다\n"
        "  none       걸리는 게 없다\n"
        "  가격이 이 동네 평균과 비슷하면 price 가 아니다. price 를 억지로\n"
        "  고르지 마라. price 는 값이 부담될 때만 쓴다.\n"
    )
    findings = label_bias(old, ("price", "message", "relevance", "none"))
    assert any("price" in f.detail for f in findings)


def test_incident_0814_score_tied_rule() -> None:
    """'61 이상이면 none' — 척도표와 맞물려 none 이 도달 불가능했다."""
    old = "`intent` 를 61 이상으로 줬다면 `none` 을 골라라"
    assert score_tied_label_rule(old)
    assert not score_tied_label_rule("걸리는 게 없으면 none 이다. 점수가 몇 점이든 상관없다")


def test_incident_0818_missing_example() -> None:
    """relevance 만 예시가 없어 0건 — 한 줄 넣자 1→8 로 뒤집혔다."""
    old = (
        '  "가격은 괜찮지만, 늘 가던 곳이 있어서"   → alternative\n'
        '  "정보가 부족해요"                        → message\n'
        '  "가격이 부담스럽네요"                    → price\n'
        '  "10분 컷이 편해 보이네요"                → none\n'
    )
    assert missing_label_example(old, SELECTABLE) == [("missing_label_example", "relevance")]


def test_incident_0817_json_keyword() -> None:
    """'json' 없는 프롬프트 — OpenAI 가 400, 폴백이 조용히 삼켰다."""
    assert json_keyword('번호 순서대로 돌려준다.\n{"labels": [...]}')
    assert not json_keyword("**JSON** 으로 돌려준다.")


def test_path_field_is_a_value_not_free_text() -> None:
    """evidence 의 path 는 자유 텍스트가 아니다 — 실제 경로가 맞다.

    판별기 첫 판이 이걸 결함으로 잡았다(가짜 양성). 자리표시로 바꾸면
    모델이 그걸 베껴 근거 대조에서 탈락한다 — 세로줄과 같은 자리다.
    """
    assert not copyable_free_text('"path": "age_share.30"')


def test_enum_field_must_keep_a_real_value() -> None:
    """enum 에 자리표시를 넣으면 그걸 베껴 Literal 검증에서 탈락한다.

    2026-08-18 에 내가 실제로 저지르려던 실수다 — 기존 테스트가 막았다.
    """
    bad = '"resistance": "<위 다섯 중 하나>"'
    ok = '"resistance": "price"'
    enum = {"resistance": set(get_args(Resistance))}
    assert copyable_free_text(bad, enum_fields=enum)
    assert not copyable_free_text(ok, enum_fields=enum)


# --- 현재 프롬프트가 전부 통과하는가 ----------------------------------------


def _resistance_block(prompt: str) -> str:
    return prompt.split("**resistance**")[1].split("**evidence**")[0]


@pytest.mark.parametrize("name", ["SYSTEM", "SUMMARY_SYSTEM", "RESISTANCE_SYSTEM"])
def test_current_prompt_is_clean(name: str) -> None:
    prompt = getattr(evaluator, name)
    assert not pipe_placeholder(prompt), name
    assert not amount_in_example(prompt), name
    assert not json_keyword(prompt), name
    assert not score_tied_label_rule(prompt), name


def test_current_system_example_is_clean() -> None:
    enum = {"resistance": set(get_args(Resistance))}
    example = evaluator.SYSTEM.split("아래 JSON 형식으로만 답해라.")[1]
    assert not copyable_free_text(example, enum_fields=enum)


def test_current_resistance_block_is_unbiased() -> None:
    assert not label_bias(_resistance_block(evaluator.SYSTEM), SELECTABLE)


def test_current_classifier_covers_every_label() -> None:
    assert not missing_label_example(evaluator.RESISTANCE_SYSTEM, SELECTABLE)
