"""주소 → 패널 → 평가 → 결과. **관통 경로 하나.**

이 파일이 있기 전까지 부품은 다 있는데 이어 붙인 곳이 없었다.
`build_features`(A) 와 `evaluate`(B) 는 각자 테스트를 통과했지만 둘을 실제로
연결해 끝까지 돌려본 적이 한 번도 없었다. 여기서 잇는다.

평가 자체는 하지 않는다 — `evaluator.evaluate()` 를 부르기만 한다.
여기가 하는 일은 셋뿐이다: 주소로 패널 만들기, dict→Pydantic 변환, 결과 캐시.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from app_core.panel.evaluator import evaluate
from app_core.panel.features import build_features
from app_core.panel.panel_builder import build_panel
from app_core.panel.schemas import EvaluationResult, Panel, Persona, TradeAreaFeatures
from app_core.schema import AdBrief, CopyCandidate, Store

#: 같은 광고 = 같은 결과를 **보장**하기 위한 캐시.
#:
#: `temperature=0` 만으로는 안 된다. 실측: 같은 입력 3회에 점수가 53.4 / 53.5 /
#: 63.4 로 갈렸고 `seed=0` 을 줘도 마찬가지였다(system_fingerprint 는 동일).
#: OpenAI 의 결정성은 보장이 아니라 best-effort 라 모델 설정으로는 못 막는다.
#: 사장님이 같은 광고를 두 번 넣었을 때 점수가 10점 튀면 신뢰가 깨지므로
#: 결과를 통째로 재사용한다. 광고를 고치면 키가 바뀌어 다시 평가한다.
#:
# ponytail: 프로세스 메모리라 서버를 재시작하면 날아간다. 여러 대로 띄우거나
# 재시작 후에도 유지해야 하면 DB 로 옮긴다 — 지금은 시연 한 판이 목적이다.
_CACHE: dict[str, EvaluationResult] = {}


def to_panel(features: dict[str, Any], personas: list[dict[str, Any]]) -> Panel:
    """A 의 dict 산출물을 B 의 Pydantic 계약으로 옮긴다.

    `TradeAreaFeatures` 가 `extra="ignore"` 라 스키마에 없는 키는 조용히 버려진다.
    지금 버려지는 것은 `match_distance_m` 하나다 (매칭 신뢰도 — 화면용이라
    평가 프롬프트에는 필요 없다). 나머지 7개는 수호님이 스키마에 넣어주셨다.
    """
    return Panel(
        features=TradeAreaFeatures(**features),
        personas=[Persona(**p) for p in personas],
    )


def _key(store: Store, brief: AdBrief, copy: CopyCandidate, ad_id: str) -> str:
    parts = (store.address, store.industry, brief.model_dump_json(), copy.model_dump_json(), ad_id)
    return sha256("\x00".join(parts).encode()).hexdigest()


def review(
    store: Store,
    brief: AdBrief,
    copy: CopyCandidate,
    *,
    ad_id: str = "ad",
    coord: tuple[float, float] | None = None,
    **kw: Any,
) -> EvaluationResult:
    """가게 주소로 패널을 만들고 광고 1건을 평가받는다.

    `coord` 는 `build_features` 와 같은 뜻 — 넘기면 카카오 호출을 건너뛴다.
    테스트에서 외부 API 를 부르지 않기 위한 통로다 (AGENTS.md).
    나머지 키워드 인자(`client`·`summarize`·`sigma_max`)는 `evaluate` 로 넘어간다.
    """
    key = _key(store, brief, copy, ad_id)
    if key not in _CACHE:
        features = build_features(store.address, store.industry, coord=coord)
        panel = to_panel(features, build_panel(features))
        _CACHE[key] = evaluate(panel, store, brief, copy, ad_id=ad_id, **kw)
    return _CACHE[key]
