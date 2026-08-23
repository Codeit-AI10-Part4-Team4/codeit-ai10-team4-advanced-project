"""설치·CI 사슬이 도는지 확인하는 스모크 테스트.

외부 API 는 부르지 않는다 (AGENTS.md). 상권 조회는 좌표를 직접 넘겨
카카오 지오코딩을 건너뛰고, 데이터는 저장소에 있는 data/panel.duckdb 를 읽는다.
"""

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.main import app

client = TestClient(app)

#: 망원동 근처. 좌표를 주면 KAKAO_REST_KEY 없이 돈다.
MANGWON = {
    "address": "서울시 마포구 망원동 123-4",
    "industry": "korean_food",
    "lat": 37.5561,
    "lon": 126.9018,
}

#: 상권 데이터가 없는 환경에서는 상권 테스트를 건너뛴다.
has_db = pytest.mark.skipif(
    not Path("data/panel.duckdb").exists(), reason="data/panel.duckdb 가 없다"
)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_업종_목록은_id_label_emoji_만_준다() -> None:
    """프롬프트용 필드까지 내려보내면 그게 바뀔 때마다 화면이 같이 흔들린다."""
    response = client.get("/industries")
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 10
    assert set(body[0]) == {"id", "label", "emoji"}
    assert any(i["id"] == "korean_food" for i in body)


@has_db
def test_상권은_키_없이_실측을_돌려준다() -> None:
    """좌표를 주면 외부 호출이 하나도 없다. 값은 서울시 원본에서 온다.

    숫자를 못 박지 않고 형식·범위만 본다 — 분기가 바뀌면 값도 바뀐다.
    """
    response = client.get("/trade-area", params=MANGWON)
    assert response.status_code == 200
    body = response.json()
    assert body["quarter"].isdigit() and len(body["quarter"]) == 5  # YYYYQ
    assert body["avg_ticket"] > 0
    assert 0 <= body["peak_share"] <= 1
    assert body["peak_time"]


@has_db
def test_좌표는_둘_다_주거나_둘_다_빼야_한다() -> None:
    """하나만 주면 나머지를 지오코딩해야 하는데, 키가 없으면 거기서 죽는다.
    무엇이 잘못됐는지 입구에서 말해준다."""
    params = {k: v for k, v in MANGWON.items() if k != "lon"}
    assert client.get("/trade-area", params=params).status_code == 400


def test_주소가_비면_거절한다() -> None:
    response = client.get("/trade-area", params={"address": "", "industry": "cafe"})
    assert response.status_code == 422


# ── 오래 걸리는 작업 ────────────────────────────────────────────
# 확산 모델은 부르지 않는다 (한 장에 18초). 폴링 계약만 본다.


def _wait(job_id: str, timeout: float = 3.0) -> dict[str, Any]:
    """끝날 때까지 물어본다 — 화면이 하는 일과 같다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body: dict[str, Any] = client.get(f"/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"{timeout}초 안에 안 끝났다")


def test_등록하면_바로_번호를_주고_나중에_끝난다() -> None:
    """느린 작업이라도 등록은 즉시 끝나야 한다. 그게 이 구조의 이유다."""
    jobs.clear()

    def 느리다() -> str:
        time.sleep(0.05)
        return "다 됐다"

    job = jobs.submit(느리다)
    assert client.get(f"/jobs/{job.id}").json()["status"] in {"running", "done"}
    assert _wait(job.id)["status"] == "done"


def test_작업이_터져도_서버는_살아있고_이유를_말한다() -> None:
    """스레드에서 삼키지 않으면 화면은 영원히 running 을 본다."""
    jobs.clear()

    def 터진다() -> None:
        raise ValueError("모델을 못 찾았습니다")

    body = _wait(jobs.submit(터진다).id)
    assert body["status"] == "failed"
    assert body["error"] is not None and "모델을 못 찾았습니다" in body["error"]
    assert body["image_url"] is None


def test_없는_번호는_404() -> None:
    """서버를 재시작하면 진행 중이던 작업이 날아간다. 화면이 영원히
    기다리지 않도록 없다고 말해준다."""
    assert client.get("/jobs/그런건없다").status_code == 404
    assert client.get("/jobs/그런건없다/image").status_code == 404


def test_끝나기_전에는_이미지를_안_준다() -> None:
    jobs.clear()

    def 아직() -> None:
        time.sleep(0.3)

    job = jobs.submit(아직)
    assert client.get(f"/jobs/{job.id}/image").status_code == 404


def test_이미지_요청은_필수값이_빠지면_거절한다() -> None:
    """등록 단계에서 걸러야 한다 — 18초 뒤에 "product 가 없다"고 하면 늦다."""
    assert client.post("/ads/image", json={"store_name": "가게"}).status_code == 422
