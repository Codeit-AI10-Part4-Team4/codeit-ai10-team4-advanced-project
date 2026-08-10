"""관통 경로 검증 — 주소 → 패널 → 평가 → 집계.

실제 API 는 부르지 않는다 (AGENTS.md). 가짜 클라이언트는 수호님 평가 테스트의
것을 그대로 쓴다 — 같은 계약을 두 번 흉내내면 어긋난다.

여기 있는 것은 **반증 테스트**다. "동네 데이터가 실제로 결과를 바꾸는가",
"같은 광고에 같은 점수가 나오는가" — 못 보이면 상권 데이터는 장식이다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel.features import DB_PATH, build_features
from app_core.panel.panel_builder import build_panel
from app_core.panel.review import review, to_panel
from app_core.schema import AdBrief, CopyCandidate, Store, StoreInput

from .test_evaluator import FakeClient, _good

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="data/panel.duckdb 없음")

BRIEF = AdBrief(goal="copy", product="크로플", price=6000, situation="신메뉴")
COPY = CopyCandidate(headline="점심 후 달달한 크로플", sub="6,000원")
YEOKSAM = (127.0365, 37.5005)
HONGDAE = (126.9250, 37.5610)


def _store(address: str = "서울 강남구 테헤란로 152") -> Store:
    base = StoreInput(industry="cafe", name="테스트카페", address=address)
    return Store(**base.model_dump(), id=1, user_id=1)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """결과 캐시는 프로세스 전역이라 테스트끼리 샌다."""
    from app_core.panel import review as mod

    mod._CACHE.clear()


def _honest(coord: tuple[float, float]) -> FakeClient:
    """그 동네 패널의 근거를 그대로 인용하는 성실한 모델."""
    features = build_features("", "cafe", coord=coord)
    # 수호님 FakeClient 는 프롬프트("## 나")에서 demo 를 뽑아 넘긴다 — persona_id 가 아니다.
    by_demo = {p.demo: p for p in to_panel(features, build_panel(features)).personas}

    def reply(demo: str, _calls: list[str]) -> dict[str, Any]:
        p = by_demo[demo]
        return _good(p, attention=50 + int(p.persona_id[1:]))

    return FakeClient(reply=reply)


def test_주소만_넣으면_결과가_나온다() -> None:
    r = review(_store(), BRIEF, COPY, client=_honest(YEOKSAM), coord=YEOKSAM)
    assert r.area_nm == "역삼역"
    assert set(r.scores) == {"attention", "message", "intent"}
    assert r.excluded_cnt == 0
    assert len(r.persona_comments) == 12


def test_동네를_바꾸면_결과가_달라진다() -> None:
    """반증 테스트 — 동네 데이터가 장식이 아님을 보인다.

    같은 광고·같은 응답 규칙인데 역삼(출퇴근)과 홍대(주거·유흥)는 페르소나
    가중치가 달라 가중 평균이 달라져야 한다. 안 달라지면 상권 데이터가
    아무 일도 안 하는 것이다.
    """
    a = review(_store(), BRIEF, COPY, client=_honest(YEOKSAM), coord=YEOKSAM)
    b = review(
        _store("서울 마포구 와우산로 94"), BRIEF, COPY, client=_honest(HONGDAE), coord=HONGDAE
    )
    assert a.area_nm != b.area_nm
    assert a.scores != b.scores


def test_같은_광고는_다시_평가하지_않는다() -> None:
    """재현성 보장 — temperature=0 만으로는 실측에서 점수가 10점까지 튀었다."""
    c = _honest(YEOKSAM)
    a = review(_store(), BRIEF, COPY, client=c, coord=YEOKSAM)
    n = len(c.calls)
    b = review(_store(), BRIEF, COPY, client=c, coord=YEOKSAM)
    assert len(c.calls) == n  # 두 번째는 캐시 — 모델을 안 부른다
    assert a.scores == b.scores
    assert [x.comment for x in a.persona_comments] == [x.comment for x in b.persona_comments]


def test_광고를_고치면_다시_평가한다() -> None:
    from app_core.panel import review as mod

    c = _honest(YEOKSAM)
    review(_store(), BRIEF, COPY, client=c, coord=YEOKSAM)
    review(_store(), BRIEF, CopyCandidate(headline="완전히 다른 문구"), client=c, coord=YEOKSAM)
    assert len(mod._CACHE) == 2


def test_요청한_피처가_평가에_실린다() -> None:
    """work_ratio 등 7개는 수호님이 스키마에 넣어주셨다. 버려지지 않는지 확인."""
    f = build_features("", "cafe", coord=YEOKSAM)
    panel = to_panel(f, build_panel(f))
    for name in ("work_ratio", "worker_pop", "resident_pop", "apt_avg_price", "back_age_share"):
        assert hasattr(panel.features, name), name
    assert panel.features.work_ratio == f["work_ratio"]
