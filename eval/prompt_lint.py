"""프롬프트 결함 판별기 — 실측으로 확인된 실패 유형만 검사한다.

LLM 을 쓰지 않는다. 문자열만 보고 결정적으로 판별한다.

이 프로젝트에서 프롬프트 결함을 다섯 번 만났고, 다섯 번 다 사람이 실제
API 를 돌려서야 발견했다. 단위 테스트는 매번 전부 통과하고 있었다.

    8/07  세로줄 예시            21/23 콜이 "price|message" 를 베껴 탈락
    8/11  예시 속 금액           '런치 세트 8,900원' — 없는 가격을 지어냄
    8/13  베낄 수 있는 예시 문장  제안 18개 중 8개가 예시와 글자까지 동일
    8/14  라벨 편향·점수 문턱     price 만 5회 언급 + "61 이상이면 none"
                                → 금액 없는 광고에 12/12 price
    8/18  예시 없는 라벨          relevance 만 예시가 없어 0건
                                (한 줄 넣자 alternative 7→0, relevance 1→8)

    번외 8/17  "json" 단어 누락 — OpenAI json_object 가 400 을 내는데
               폴백이 조용히 삼켜 "고쳐도 안 바뀐다" 로 오판할 뻔했다

공통 기전은 하나다 — **모델은 지시를 읽지 않고 예시를 읽는다.** 예시가
있으면 베끼고, 없으면 그 답을 안 한다. 금지 지시("몰아 쓰지 마라",
"비슷하면 price 가 아니다", "베끼지 마라")는 다섯 번 다 무시됐다.

그래서 이 판별기의 규칙은 전부 "무엇을 하지 마라"가 아니라 **예시와
구조가 어떤 꼴이어야 하는가**다. 각 검사는 실제 사고 하나에 뿌리를 두고,
그 사고의 원본 문자열이 tests/eval/test_prompt_lint.py 에 회귀 코퍼스로
박혀 있다 — 검사를 고치다 사고를 다시 통과시키면 거기서 걸린다.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple


class Finding(NamedTuple):
    """결함 한 건. check 는 아래 검사 이름, detail 은 걸린 문자열."""

    check: str
    detail: str


#: JSON 예시 안에서 자리표시로 인정하는 꼴.
_PLACEHOLDER: Final = re.compile(r"^<.+>$")

#: 원 단위 금액.
_AMOUNT: Final = re.compile(r"\d[\d,]*\s*원")

#: JSON 예시 블록의 문자열 값. ("키": "값") 쌍의 값 쪽만 잡는다.
_JSON_STR_VALUE: Final = re.compile(r'"\w+"\s*:\s*"([^"]*)"')

#: 걸림돌을 점수에 묶는 규칙의 꼴.
#: 8/14: "intent 를 61 이상으로 줬다면 none 을 골라라" 가 척도표의
#: "41~60 = 괜찮네 정도" 와 맞물려 none 이 도달 불가능했다.
_SCORE_TIED_RULE: Final = re.compile(r"\d+\s*(점|이상|이하|미만|초과)[^\n]*(골라|고른|택|답)")


def pipe_placeholder(prompt: str) -> list[Finding]:
    """따옴표 안 세로줄 — 모델이 그대로 베껴 스키마에서 탈락한다 (8/07).

    허용값 나열은 산문으로 한다("다섯 중 하나를 그대로 적는다").
    """
    return [
        Finding("pipe_placeholder", m.group(0))
        for m in re.finditer(r'"[^"\n]*\|[^"\n]*"', prompt)
    ]


def amount_in_example(prompt: str) -> list[Finding]:
    """예시 줄의 금액 — 그 금액이 답에 다시 나타난다 (8/11).

    예시 줄 = "예:" 가 붙은 줄과 JSON 예시 블록의 문자열 값.
    규칙 본문의 금액("가격은 사장님이 정한다")은 잡지 않는다.
    """
    out: list[Finding] = []
    for line in prompt.splitlines():
        if "예:" in line or "예시" in line:
            for m in _AMOUNT.finditer(line):
                out.append(Finding("amount_in_example", line.strip()))
                break
    for m in _JSON_STR_VALUE.finditer(prompt):
        if _AMOUNT.search(m.group(1)):
            out.append(Finding("amount_in_example", m.group(0)))
    return out


#: 자유 텍스트가 아닌 필드 — 실제 값이어야 하는 쪽.
#: path 는 피처 경로라 자리표시로 두면 그걸 베껴 근거 대조에서 탈락한다.
_VALUE_FIELDS: Final = frozenset({"path"})


def copyable_free_text(prompt: str, *, enum_fields: dict[str, set[str]] | None = None) -> list[Finding]:
    """JSON 예시의 자유 텍스트 값 — 자리표시가 아니면 출력에 복사된다 (8/13).

    숫자는 다르다: 실제 값이 있어야 재현성이 생긴다(아인님 실측 8/14 —
    예시를 통째로 빼면 변별력 부호가 바뀐다). 그래서 **문자열 값만** 본다.

    enum 필드(예: resistance)는 반대로 **실제 값이어야** 한다 — 자리표시를
    베끼면 Literal 검증에서 탈락한다. 세로줄 사고의 다른 얼굴이다.
    """
    enum_fields = enum_fields or {}
    out: list[Finding] = []
    for m in re.finditer(r'"(\w+)"\s*:\s*"([^"]*)"', prompt):
        field, value = m.group(1), m.group(2)
        if field in enum_fields:
            if value not in enum_fields[field]:
                out.append(Finding("enum_needs_real_value", m.group(0)))
            continue
        if field in _VALUE_FIELDS:
            # 경로·식별자는 자유 텍스트가 아니다 — 실제 값이 맞다.
            continue
        # 자유 텍스트: 자리표시( <...> )거나, 베낄 가치가 없을 만큼 짧아야 한다.
        if len(value) > 8 and not _PLACEHOLDER.match(value):
            out.append(Finding("copyable_free_text", m.group(0)))
    return out


def label_bias(block: str, labels: tuple[str, ...], *, neutral: str = "none") -> list[Finding]:
    """라벨 언급 불균형 · 순서 편향 (8/14).

    price 가 5회 언급되고 목록 첫 자리일 때, 금액 없는 광고에도 12/12 가
    price 를 골랐다. 가장 많이 말해진 단어가 답이 된다.

    규칙: 중립 라벨(none)이 맨 앞에 오고, 어떤 라벨도 중립보다 많이
    언급되지 않는다.
    """
    out: list[Finding] = []
    counts = {lab: block.count(lab) for lab in labels}
    if neutral in labels:
        for lab, n in counts.items():
            if lab != neutral and n > counts[neutral]:
                out.append(Finding("label_bias", f"{lab} {n}회 > {neutral} {counts[neutral]}회"))
        positions = {lab: block.find(lab) for lab in labels if block.find(lab) >= 0}
        if positions and min(positions, key=positions.get) != neutral:
            out.append(Finding("label_bias", f"{neutral} 이 첫 자리가 아니다"))
    return out


def missing_label_example(block: str, labels: tuple[str, ...]) -> list[Finding]:
    """예시 없는 라벨 — 그 답은 안 나온다 (8/18).

    relevance 만 예시가 없었고 나와야 할 자리에서 0건이었다.
    예시 한 줄을 넣자 alternative 7→0, relevance 1→8 로 뒤집혔다.
    예시 목록이 곧 답의 분포다.
    """
    exampled = {
        line.rsplit("→", 1)[1].strip()
        for line in block.splitlines()
        if "→" in line
    }
    return [
        Finding("missing_label_example", lab)
        for lab in labels
        if lab not in exampled
    ]


def json_keyword(prompt: str) -> list[Finding]:
    """"json" 단어 — 없으면 OpenAI json_object 모드가 400 을 낸다 (8/17).

    `{"labels": [...]}` 를 적어 두면 JSON 인 게 분명하다고 생각하기 쉽지만
    API 는 글자 그대로 "json" 을 찾는다. 폴백이 조용히 삼키면 "고쳐도
    안 바뀐다" 로 오판하게 된다.
    """
    return [] if "json" in prompt.lower() else [Finding("json_keyword", "'json' 없음")]


def score_tied_label_rule(prompt: str) -> list[Finding]:
    """걸림돌을 점수 문턱에 묶는 규칙 (8/14).

    "intent 61 이상이면 none" 이 척도표 "41~60 = 괜찮네" 와 맞물려 none 이
    도달 불가능했다. 문턱은 프롬프트가 아니라 집계 코드가 집행한다
    (aggregate.RESISTANCE_INTENT_MAX) — 모델의 자기검열에 기대지 않는다.
    """
    return [
        Finding("score_tied_label_rule", m.group(0).strip())
        for m in _SCORE_TIED_RULE.finditer(prompt)
    ]
