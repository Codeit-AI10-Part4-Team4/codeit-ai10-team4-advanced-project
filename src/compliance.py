"""광고 규제 준수 엔진 (룰 기반).

docs/02_광고규제_준수기능_설계.md 의 3단계 중 A·B 를 담당한다.

  Stage A  생성 전 — prompt_constraints() 로 금지 규칙을 문구 생성 프롬프트에 주입
  Stage B  생성 후 — scan() 으로 위반 후보 탐지, apply_alternative() 로 원클릭 교체
  Stage C  설명    — applicable_laws() 로 적용 법령 제시 (RAG 얹기 전 룰 기반 버전)

확정적 금칙어는 LLM 이 아니라 정규식으로 잡는다. 빠르고(~10ms) 정확하며 놓치지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from . import registry

SEVERITY_ORDER = {"high": 0, "medium": 1, "info": 2}
SEVERITY_LABEL = {"high": "차단 권고", "medium": "확인 필요", "info": "참고"}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    label: str
    matched: str          # 실제로 걸린 문자열
    start: int
    end: int
    severity: str
    reason: str
    alternatives: tuple[str, ...]
    law_name: str
    law_article: str

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABEL.get(self.severity, self.severity)


@lru_cache(maxsize=None)
def _compiled_rules() -> tuple[tuple[dict, re.Pattern], ...]:
    return tuple((r, re.compile(r["pattern"])) for r in registry.banned_terms())


def _rules_for(tags: frozenset[str]) -> list[tuple[dict, re.Pattern]]:
    return [
        (rule, pat)
        for rule, pat in _compiled_rules()
        if set(rule.get("legal_tags", [])) & tags
    ]


def scan(text: str, tags: set[str]) -> list[Finding]:
    """Stage B — 문구에서 위반 후보를 찾는다. 심각도 순으로 정렬해 반환."""
    if not text:
        return []

    law_index = {law["id"]: law for law in registry.laws()}
    findings: list[Finding] = []

    for rule, pattern in _rules_for(frozenset(tags)):
        law = law_index.get(rule["law_id"], {})
        for m in pattern.finditer(text):
            findings.append(
                Finding(
                    rule_id=rule["id"],
                    label=rule["label"],
                    matched=m.group(0),
                    start=m.start(),
                    end=m.end(),
                    severity=rule["severity"],
                    reason=rule["reason"],
                    alternatives=tuple(rule.get("alternatives") or []),
                    law_name=law.get("name", ""),
                    law_article=law.get("article", ""),
                )
            )

    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.start))
    return findings


def has_blocking(findings: list[Finding]) -> bool:
    return any(f.severity == "high" for f in findings)


def apply_alternative(text: str, finding: Finding, alternative: str) -> str:
    """걸린 표현을 대체 표현으로 교체한다.

    레이아웃 단계가 분리돼 있어 이 교체는 GPU 재실행 없이 즉시 반영된다.
    """
    return text[: finding.start] + alternative + text[finding.end :]


def applicable_laws(tags: set[str]) -> list[dict]:
    """Stage C — 이 광고에 적용되는 법령 목록.

    지금은 사전 매핑이다. RAG 를 얹으면 `summary`/`we_did` 를
    법령 코퍼스에서 검색한 근거로 대체한다.
    """
    return [law for law in registry.laws() if set(law.get("legal_tags", [])) & tags]


def prompt_constraints(tags: set[str]) -> str:
    """Stage A — 문구 생성 프롬프트에 주입할 금지 규칙 텍스트.

    실제 LLM 을 붙이면 이 문자열이 시스템 프롬프트로 들어간다.
    이게 있어야 애초에 위반 문구가 생성되지 않는다.
    """
    lines = ["다음 표현은 광고 관련 법령상 사용할 수 없습니다. 절대 쓰지 마세요."]
    for rule, _ in _rules_for(frozenset(tags)):
        if rule["severity"] == "info":
            continue
        examples = rule["pattern"].replace("\\", "").replace("|", ", ")
        lines.append(f"- {rule['label']}: {examples} ({rule['reason']})")
    return "\n".join(lines)
