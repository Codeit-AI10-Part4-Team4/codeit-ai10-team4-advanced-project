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
from app_core.panel.review import Ranked, bands, rank, rank_key, review, to_panel
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


class Honest(FakeClient):
    """근거를 그대로 인용하는 성실한 모델. **서사 콜까지** 받는다.

    수호님 `FakeClient` 는 평가·요약 두 종류만 알아서, 서사 프롬프트가 오면
    페르소나 이름을 못 찾고 터진다. 여기서 한 겹 감싼다.
    """

    def complete_json(self, system: str, user: str) -> dict:
        if system.startswith("상권 데이터를 손님 소개글로"):
            self.calls.append("narrate")
            ids = [ln.split(":")[0][2:] for ln in user.splitlines() if ln.startswith("- p")]
            return {pid: f"{pid} 손님의 이야기" for pid in ids}
        return super().complete_json(system, user)


def _honest(coord: tuple[float, float]) -> Honest:
    features = build_features("", "cafe", coord=coord)
    # 수호님 FakeClient 는 프롬프트("## 나")에서 demo 를 뽑아 넘긴다 — persona_id 가 아니다.
    by_demo = {p.demo: p for p in to_panel(features, build_panel(features)).personas}

    def reply(demo: str, _calls: list[str]) -> dict[str, Any]:
        p = by_demo[demo]
        return _good(p, attention=50 + int(p.persona_id[1:]))

    return Honest(reply=reply)


def _ranked(intent: float, attention: float = 60.0, defects: int = 0) -> Ranked:
    """정렬만 검증하므로 결과는 최소 필드로 만든다."""
    from app_core.panel.contrast import Note
    from app_core.panel.schemas import EvaluationResult

    return Ranked(
        copy=COPY,
        result=EvaluationResult(
            ad_id="x",
            scores={"attention": attention, "message": 70.0, "intent": intent},
            confidence="ok",
            max_metric_std=0.0,
            top_resistance=[],
            persona_comments=[],
            area_nm="역삼역",
            quarter="20261",
            is_fallback=False,
            demo_coverage=0.9,
        ),
        defects=[Note(kind="product", text="", evidence=[])] * defects,
    )


def _keys(*rs: Ranked) -> list[tuple[int, int, float, int]]:
    """`rank()` 와 같은 순서로 정렬 키를 만든다.

    무리 짓기(`bands`)를 거쳐야 `rank_key` 가 실제로 쓰이는 모양이 된다.
    전에는 `rank_key` 만 따로 불러서, 무리를 잘못 짓는 결함을 테스트가 못 봤다.
    """
    band = bands([r.result.scores["intent"] for r in rs])
    return [rank_key(r, n, band[n]) for n, r in enumerate(rs)]


def test_방문의향이_높은_문구가_앞에_온다() -> None:
    """사장님이 원하는 결과 그 자체라 첫 기준으로 둔다."""
    keys = _keys(*(_ranked(intent=i) for i in [46.0, 54.0, 50.0]))
    assert [n for *_, n in sorted(keys)] == [1, 2, 0]


def test_잡음보다_작은_차이는_차이가_아니다() -> None:
    """실측(2026-08-13): 1·2위가 반올림해 둘 다 52 인데 1위에만 결함이 있었다.

    사장님 화면에서 "1위" 바로 밑에 경고가 뜨는 모양이 된다. 0.1점 차로 결함 있는
    문구가 1등이 되면 안 된다.
    """
    keys = _keys(
        _ranked(intent=52.4, defects=1),  # 아주 조금 높지만 결함 있음
        _ranked(intent=52.0, defects=0),  # 결함 없음
    )
    assert min(keys)[3] == 1


def test_격자선을_사이에_둔_두_후보도_같은_무리다() -> None:
    """고정 격자로 묶던 시절의 결함.

    `round(intent / 2.0)` 은 52.9 를 26 번, 53.1 을 27 번으로 갈랐다. 0.2 점
    차이는 재실행 잡음 0.7 보다 작은데도 결함 있는 쪽이 1위가 됐다 — 위 테스트가
    고른 52.4/52.0 은 마침 같은 칸이라 이 구멍을 지나쳤다.
    """
    keys = _keys(_ranked(intent=53.1, defects=1), _ranked(intent=52.9, defects=0))
    assert min(keys)[3] == 1


def test_잡음보다_큰_차이는_결함을_이긴다() -> None:
    """결함이 있어도 손님들이 확실히 더 좋아하면 그쪽이 1위다."""
    keys = _keys(_ranked(intent=58.0, defects=1), _ranked(intent=50.0, defects=0))
    assert min(keys)[3] == 0


def test_결함까지_같으면_눈길이_가른다() -> None:
    """눈길은 신호가 가장 큰 지표다 (실측: 후보 3개 폭 5.5 vs 잡음 0.7)."""
    keys = _keys(*(_ranked(intent=52.0, attention=a) for a in [59.8, 65.3, 59.8]))
    assert min(keys)[3] == 1


def test_전부_같으면_만든_순서를_지킨다() -> None:
    keys = _keys(*(_ranked(intent=52.0) for _ in range(3)))
    assert [n for *_, n in sorted(keys)] == [0, 1, 2]


def test_후보마다_하나씩_돌려준다() -> None:
    copies = [COPY, CopyCandidate(headline="크로플 6,000원", sub="")]
    out = rank(_store(), BRIEF, copies, client=_honest(YEOKSAM), coord=YEOKSAM)
    assert len(out) == 2
    assert {r.copy.headline for r in out} == {c.headline for c in copies}


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


def test_서사를_LLM_이_쓴다() -> None:
    """스텁 문장을 쓰면 12명이 나이·성별만 다른 같은 글을 받는다.

    실측(2026-08-10): 손님 1명이 받는 프롬프트 21줄 중 12명 사이에 다른 줄이
    5줄뿐이었고, 그중 3줄은 숫자였다. 서사가 스텁이라 그랬다.
    """
    c = _honest(YEOKSAM)
    r = review(_store(), BRIEF, COPY, client=c, coord=YEOKSAM)
    assert "narrate" in c.calls  # 서사 콜이 실제로 나갔다
    assert c.calls.count("narrate") == 1  # 12명을 배치 1콜로
    assert len(r.persona_comments) == 12


def test_스키마가_버리는_피처를_적어둔다() -> None:
    """`extra="ignore"` 는 조용히 버려서, 주석이 틀려도 아무도 못 잡는다.

    실제로 틀려 있었다 — "버려지는 것은 match_distance_m 하나"라고 적혀 있었는데
    그건 스키마에 있었고, 정작 age_ticket 두 개가 버려지고 있었다.
    버리는 목록이 바뀌면 여기서 걸리게 둔다.
    """
    from app_core.panel.schemas import TradeAreaFeatures

    f = build_features("", "cafe", coord=YEOKSAM)
    dropped = set(f) - set(TradeAreaFeatures.model_fields)
    assert dropped == {"age_ticket", "age_ticket_base"}
