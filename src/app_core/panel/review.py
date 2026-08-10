"""주소 → 패널 → 평가 → 결과. **관통 경로 하나.**

이 파일이 있기 전까지 부품은 다 있는데 이어 붙인 곳이 없었다.
`build_features`(A) 와 `aggregate`(B) 는 각자 테스트를 통과했지만 둘을 실제로
연결해 끝까지 돌려본 적이 한 번도 없었다. 여기서 잇는다.

**의도적으로 가장 단순하게 짰다.** 평가 호출은 12명을 배치 1콜로 처리한다.
07 §7.2 의 "페르소나별 병렬 호출"이 아니다 — 관통이 먼저고 품질은 그다음이다.
평가 호출은 B 영역(수호님)이므로 `_ask` 는 갈아끼울 자리로 남겨둔다.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Protocol

from app_core.panel.aggregate import aggregate
from app_core.panel.features import build_features
from app_core.panel.panel_builder import build_panel
from app_core.panel.schemas import (
    EvaluationResult,
    FeatureRef,
    Panel,
    Persona,
    PersonaEval,
    TradeAreaFeatures,
)
from app_core.schema import AdBrief, CopyCandidate, Store


class _Client(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


SYSTEM = """동네 가게 광고를 손님 입장에서 본다. 손님 여러 명이 각자 답한다.

각 손님마다:
  attention 0~100  눈에 들어오는가
  message   0~100  무엇을 파는지 알겠는가
  intent    0~100  가볼 마음이 드는가
  resistance       가장 큰 걸림돌 하나 (none 이면 없음)
  comment          한 문장. 손님 말투로
  evidence         아래 "인용 가능한 값"에서 **그대로** 골라 1개 이상

**evidence 는 반드시 주어진 목록에서 path 와 value 를 글자 그대로 옮긴다.**
값을 고치거나 새로 만들면 그 손님 답은 통째로 버려진다.

응답은 JSON 하나:
{"p01": {"attention": 70, "message": 80, "intent": 60, "resistance": "price",
         "comment": "문장", "evidence": [{"path": "age_share.30", "value": 0.4}]}, ...}"""


def to_panel(features: dict[str, Any], personas: list[dict[str, Any]]) -> Panel:
    """A 의 dict 산출물을 B 의 Pydantic 계약으로 옮긴다.

    `TradeAreaFeatures` 가 `extra="ignore"` 라 스키마에 아직 없는 필드
    (`work_ratio` 등 7개)는 조용히 버려진다. 그래서 평가 프롬프트에 안 실린다 —
    수호님께 필드 추가를 요청해둔 상태다.
    """
    return Panel(
        features=TradeAreaFeatures(**features),
        personas=[Persona(**p) for p in personas],
    )


def build_prompt(panel: Panel, copies: list[CopyCandidate], brief: AdBrief) -> str:
    f = panel.features
    ad = "\n".join(f"  {c.headline}" + (f" / {c.sub}" if c.sub else "") for c in copies)
    quotable = "\n".join(
        f'  {{"path": "{e.path}", "value": {e.value}}}' for p in panel.personas for e in p.evidence
    )
    return (
        f"## 광고\n{ad}\n"
        f"파는 것: {brief.product}"
        + (f" / {brief.price:,}원" if brief.show_price else "")
        + (f" / {brief.situation}" if brief.situation else "")
        + f"\n\n## 동네\n{f.area_nm} ({f.gu_nm} {f.dong_nm}), {f.category_nm}, "
        f"객단가 {f.avg_ticket:,}원, 경쟁 점포 {f.competitor_cnt}곳\n\n"
        "## 손님\n"
        + "\n".join(
            f"- {p.persona_id} ({p.demo}, 비중 {p.weight * 100:.1f}%): {p.narrative}"
            for p in panel.personas
        )
        + "\n\n## 인용 가능한 값\n"
        + quotable
    )


#: 같은 광고 = 같은 결과를 **보장**하기 위한 캐시. 키는 프롬프트 해시다.
#:
#: `temperature=0` 만으로는 안 된다. 실측: 같은 입력 3회에 점수가 53.4 / 53.5 /
#: 63.4 로 갈렸고 `seed=0` 을 줘도 마찬가지였다(system_fingerprint 는 동일).
#: OpenAI 의 결정성은 보장이 아니라 best-effort 라 모델 설정으로는 못 막는다.
#: 사장님이 같은 광고를 두 번 넣었을 때 점수가 10점 튀면 신뢰가 깨지므로
#: 호출 자체를 재사용한다. 광고를 고치면 키가 바뀌어 다시 부른다.
#:
# ponytail: 프로세스 메모리라 서버를 재시작하면 날아간다. 여러 대로 띄우거나
# 재시작 후에도 유지해야 하면 DB 로 옮긴다 — 지금은 시연 한 판이 목적이다.
_CACHE: dict[str, dict] = {}


def _ask(
    panel: Panel, copies: list[CopyCandidate], brief: AdBrief, client: _Client
) -> list[PersonaEval]:
    """배치 1콜. 응답이 스키마에 안 맞는 손님은 조용히 빠진다 — 집계가 탈락으로 센다."""
    prompt = build_prompt(panel, copies, brief)
    key = sha256(f"{SYSTEM}\x00{prompt}".encode()).hexdigest()
    if key not in _CACHE:
        _CACHE[key] = client.complete_json(SYSTEM, prompt)
    reply = _CACHE[key]
    out: list[PersonaEval] = []
    for p in panel.personas:
        raw = reply.get(p.persona_id)
        if not isinstance(raw, dict):
            continue
        try:
            out.append(
                PersonaEval(
                    persona_id=p.persona_id,
                    evidence=[FeatureRef(**e) for e in raw.get("evidence", [])],
                    **{k: v for k, v in raw.items() if k != "evidence"},
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def review(
    store: Store,
    brief: AdBrief,
    copies: list[CopyCandidate],
    *,
    ad_id: str = "ad",
    client: _Client | None = None,
    coord: tuple[float, float] | None = None,
) -> EvaluationResult:
    """가게 주소로 패널을 만들고 광고를 평가해 집계 결과를 낸다.

    `client` 를 넘기면 그것을 쓴다 (테스트용). 안 넘기면 `MODEL_PROFILE` 을 따른다.
    `coord` 는 `build_features` 와 같은 뜻 — 넘기면 카카오 호출을 건너뛴다.
    테스트에서 외부 API 를 부르지 않기 위한 통로다 (AGENTS.md).
    """
    from app_core.llm import get_client

    features = build_features(store.address, store.industry, coord=coord)
    panel = to_panel(features, build_panel(features))
    evals = _ask(panel, copies, brief, client or get_client())
    return aggregate(panel, evals, ad_id=ad_id)
