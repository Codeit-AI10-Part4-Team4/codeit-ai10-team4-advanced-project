"""관통 경로 검증 — 주소 → 패널 → 평가 → 집계.

실제 API 는 부르지 않는다 (AGENTS.md). 가짜 클라이언트로 응답을 흉내낸다.
DuckDB 가 있어야 하므로 없으면 건너뛴다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel.features import DB_PATH
from app_core.panel.review import build_prompt, review, to_panel
from app_core.schema import AdBrief, CopyCandidate, Store

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="data/panel.duckdb 없음")

STORE = Store(
    id=1, user_id=1, industry="cafe", name="테스트카페", address="서울 강남구 테헤란로 152"
)
BRIEF = AdBrief(goal="copy", product="크로플", price=6000)
COPIES = [CopyCandidate(headline="점심 후 달달한 크로플", sub="6,000원")]
YEOKSAM = (127.0365, 37.5005)
HONGDAE = (126.9250, 37.5610)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """평가 응답 캐시는 프로세스 전역이라 테스트끼리 샌다."""
    from app_core.panel import review as mod

    mod._CACHE.clear()


class FakeClient:
    """패널의 evidence 를 그대로 인용하는 성실한 모델."""

    def __init__(self, *, cite_wrong: bool = False) -> None:
        self.cite_wrong = cite_wrong
        self.prompt = ""

    def complete_json(self, system: str, user: str) -> dict:
        self.prompt = user
        ids = [line.split()[1] for line in user.splitlines() if line.startswith("- p")]
        out: dict[str, Any] = {}
        for i, pid in enumerate(ids):
            path, value = self._evidence_for(user, pid)
            out[pid] = {
                "attention": 50 + i,
                "message": 60,
                "intent": 40,
                "resistance": "price",
                "comment": f"{pid} 손님의 한마디",
                "evidence": [{"path": path, "value": 9.99 if self.cite_wrong else value}],
            }
        return out

    @staticmethod
    def _evidence_for(prompt: str, pid: str) -> tuple[str, float]:
        # "인용 가능한 값" 목록의 첫 줄을 쓴다 — 실제 모델도 여기서 골라야 한다.
        line = prompt.split("## 인용 가능한 값\n")[1].splitlines()[0]
        path = line.split('"path": "')[1].split('"')[0]
        return path, float(line.split('"value": ')[1].rstrip("}"))


def test_주소만_넣으면_결과가_나온다() -> None:
    r = review(STORE, BRIEF, COPIES, client=FakeClient(), coord=YEOKSAM)
    assert r.area_nm == "역삼역"
    assert set(r.scores) == {"attention", "message", "intent"}
    assert r.excluded_cnt == 0
    assert len(r.persona_comments) == 12


def test_지어낸_근거는_전부_탈락한다() -> None:
    """evidence 검증이 실제로 동작하는지 — 이게 없으면 근거 등급이 무의미하다."""
    from app_core.panel.aggregate import AggregationError

    with pytest.raises(AggregationError):
        review(STORE, BRIEF, COPIES, client=FakeClient(cite_wrong=True), coord=YEOKSAM)


def test_동네를_바꾸면_결과가_달라진다() -> None:
    """반증 테스트 — 동네 데이터가 장식이 아님을 보인다.

    같은 광고를 역삼(출퇴근)과 홍대(주거·유흥)에 넣으면 가중치가 달라
    가중 평균이 달라져야 한다. 안 달라지면 상권 데이터가 일을 안 하는 것이다.
    """
    hongdae = STORE.model_copy(update={"address": "서울 마포구 와우산로 94"})
    a = review(STORE, BRIEF, COPIES, client=FakeClient(), coord=YEOKSAM)
    b = review(hongdae, BRIEF, COPIES, client=FakeClient(), coord=HONGDAE)
    assert a.area_nm != b.area_nm
    assert a.scores != b.scores


def test_같은_입력이면_같은_결과다() -> None:
    """재현성 — 시연 중 같은 광고에 다른 점수가 나오면 안 된다."""
    a = review(STORE, BRIEF, COPIES, client=FakeClient(), coord=YEOKSAM)
    b = review(STORE, BRIEF, COPIES, client=FakeClient(), coord=YEOKSAM)
    assert a.scores == b.scores
    assert a.top_resistance == b.top_resistance


def test_프롬프트에_인용_가능한_값이_실린다() -> None:
    c = FakeClient()
    review(STORE, BRIEF, COPIES, client=c, coord=YEOKSAM)
    assert "## 인용 가능한 값" in c.prompt
    assert "age_share." in c.prompt
    assert "크로플" in c.prompt


def test_스키마에_없는_필드는_조용히_버려진다() -> None:
    """work_ratio 등 7개가 평가 프롬프트에 안 실리는 상태를 명시적으로 남긴다."""
    from app_core.panel.features import build_features
    from app_core.panel.panel_builder import build_panel

    f = build_features("", "cafe", coord=(127.0365, 37.5005))
    panel = to_panel(f, build_panel(f))
    assert "work_ratio" in f
    assert not hasattr(panel.features, "work_ratio")
    assert "work_ratio" not in build_prompt(panel, COPIES, BRIEF)


def test_같은_광고는_모델을_다시_부르지_않는다() -> None:
    """재현성 보장 — temperature=0 만으로는 실측에서 점수가 10점까지 튀었다."""

    calls: list[int] = []

    class Counting(FakeClient):
        def complete_json(self, system: str, user: str) -> dict:
            calls.append(1)
            return super().complete_json(system, user)

        @property
        def n(self) -> int:
            return len(calls)

    a = review(STORE, BRIEF, COPIES, client=Counting(), coord=YEOKSAM)
    b = review(STORE, BRIEF, COPIES, client=Counting(), coord=YEOKSAM)
    assert len(calls) == 1  # 두 번째는 캐시
    assert a.scores == b.scores
    assert [c.comment for c in a.persona_comments] == [c.comment for c in b.persona_comments]


def test_광고를_고치면_다시_부른다() -> None:
    from app_core.panel import review as mod

    review(STORE, BRIEF, COPIES, client=FakeClient(), coord=YEOKSAM)
    other = [CopyCandidate(headline="완전히 다른 문구")]
    review(STORE, BRIEF, other, client=FakeClient(), coord=YEOKSAM)
    assert len(mod._CACHE) == 2
