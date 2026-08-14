"""주소 → 패널 → 평가 → 결과. **관통 경로 하나.**

이 파일이 있기 전까지 부품은 다 있는데 이어 붙인 곳이 없었다.
`build_features`(A) 와 `evaluate`(B) 는 각자 테스트를 통과했지만 둘을 실제로
연결해 끝까지 돌려본 적이 한 번도 없었다. 여기서 잇는다.

평가 자체는 하지 않는다 — `evaluator.evaluate()` 를 부르기만 한다.
여기가 하는 일은 셋뿐이다: 주소로 패널 만들기, dict→Pydantic 변환, 결과 캐시.
"""

from __future__ import annotations

from functools import partial
from hashlib import sha256
from typing import Any, Final, NamedTuple

from app_core.panel.contrast import Note, copy_defects
from app_core.panel.evaluator import evaluate
from app_core.panel.features import build_features
from app_core.panel.narrator import narrate
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


class Ranked(NamedTuple):
    """후보 하나의 평가 결과와 문구 결함."""

    copy: CopyCandidate
    result: EvaluationResult
    defects: list[Note]


#: 이보다 벌어져야 "1등이 낫다"고 말한다. 그 아래면 "비슷합니다"라고 해야 한다.
#:
#: 재실행 잡음을 재서 정했다 (2026-08-13, 같은 광고 2회씩):
#:
#:     좋은 광고   눈길 63.8 / 63.8   이해 75.9 / 75.9   의향 54.0 / 54.0
#:     나쁜 광고   눈길 56.4 / 56.4   이해 70.4 / 70.4   의향 50.4 / 49.7
#:                                                       ↑ 관측된 최대 흔들림 0.7
#:
#: 3배인 2.0 을 기준으로 뒀다. 실제 후보 3개의 폭은 눈길 5.5 · 이해 3.6 · 의향 2.0
#: 이었으므로, 이 선이면 갈릴 때만 갈렸다고 말한다.
CLEAR_MARGIN: Final = 2.0


def rank(
    store: Store,
    brief: AdBrief,
    copies: list[CopyCandidate],
    *,
    ad_id: str = "ad",
    coord: tuple[float, float] | None = None,
    client: Any = None,
    **kw: Any,
) -> list[Ranked]:
    """후보 여러 건을 평가해 **좋은 순으로** 돌려준다.

    **절대 점수는 못 쓰고 비교는 쓸 수 있다** — 이게 이 함수가 있는 이유다.
    실측(2026-08-13): 손님들이 매기는 방문의향이 49.7~54.0 사이에만 머물러서
    "52.4점"이라는 숫자 자체로는 좋은지 나쁜지 알 수 없다. 반면 후보끼리의
    차이는 재실행 잡음(0.7)의 3~8배라 **순위는 믿을 수 있다.**

    사장님의 질문도 "이 광고 몇 점인가"가 아니라 "어느 걸 쓸까"다.

    순서는 사전식으로 정한다. 가중치를 지어내지 않으려는 것이다.
      ① 방문의향 — 사장님이 원하는 결과 그 자체. **`CLEAR_MARGIN` 폭으로 뭉쳐서**
                   본다. 잡음보다 작은 차이는 차이가 아니다
      ② 결함 적은 순 — 점수로 못 가르면 결정적 점검이 가른다
      ③ 눈길 높은 순 — 신호가 가장 큰 지표라 마지막으로 가른다
      ④ 만들어진 순  — 그래도 같으면 순서를 흔들지 않는다

    ⚠️ **콜이 후보 수만큼 든다** (1건당 약 20콜). 07 §5.1 이 "3건 전부는 비용
    3배"라며 1건만 평가하기로 한 그 3배가 맞다. 다만 그렇게 아낀 결과로 얻은
    것이 "가격"이라는 한 단어뿐이었고, 3배를 쓰면 **어느 문구를 쓸지**가 나온다.

    ⚠️ 순차로 돈다. `evaluate` 가 이미 손님 12명을 스레드로 부르고 있어서 후보까지
    병렬로 돌리면 동시 호출이 36개가 된다. 후보 3개면 1분쯤 걸린다.
    """
    out = [
        Ranked(
            copy=c,
            result=review(store, brief, c, ad_id=f"{ad_id}#{i}", coord=coord, client=client, **kw),
            defects=copy_defects(brief, c, store),
        )
        for i, c in enumerate(copies)
    ]
    return [r for _, r in sorted(enumerate(out), key=lambda p: rank_key(p[1], p[0]))]


def rank_key(r: Ranked, made_at: int) -> tuple[float, int, float, int]:
    """`rank()` 의 정렬 기준. 순수 함수라 LLM 없이 검증된다.

    **방문의향을 `CLEAR_MARGIN` 폭으로 뭉쳐서 본다.** 그러지 않으면 0.1점 차이로
    결함 있는 문구가 1등이 된다 — 실측(2026-08-13): 1위와 2위가 반올림해서 둘 다
    52 인데 1위에만 "금액이 문구에 없습니다"가 붙어, 사장님 화면에서 "1위" 바로
    밑에 경고가 뜨는 모양이 됐다. 잡음보다 작은 차이는 차이가 아니다.

    `made_at` 은 만들어진 순서 — 앞의 셋이 전부 같을 때만 쓴다.
    """
    s = r.result.scores
    band = round(s.get("intent", 0.0) / CLEAR_MARGIN)
    return (-band, len(r.defects), -s.get("attention", 0.0), made_at)


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
    client: Any = None,
    **kw: Any,
) -> EvaluationResult:
    """가게 주소로 패널을 만들고 광고 1건을 평가받는다.

    `coord` 는 `build_features` 와 같은 뜻 — 넘기면 카카오 호출을 건너뛴다.
    테스트에서 외부 API 를 부르지 않기 위한 통로다 (AGENTS.md).
    나머지 키워드 인자(`summarize`·`sigma_max`)는 `evaluate` 로 넘어간다.

    서사 생성(`narrate`)에도 **같은** `client` 를 넘긴다. 안 넘기면 서사만
    실제 API 를 불러 테스트가 외부에 나간다.
    """
    key = _key(store, brief, copy, ad_id)
    if key not in _CACHE:
        features = build_features(store.address, store.industry, coord=coord)
        # 서사를 LLM 에 맡긴다. 스텁 문장을 쓰면 12명이 나이·성별만 다른 같은
        # 문장을 받아 평가도 서로 비슷해진다 (실측: 프롬프트 21줄 중 고유 5줄).
        personas = build_panel(features, narrator=partial(narrate, client=client))
        panel = to_panel(features, personas)
        _CACHE[key] = evaluate(panel, store, brief, copy, ad_id=ad_id, client=client, **kw)
    return _CACHE[key]
