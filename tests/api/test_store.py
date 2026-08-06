"""가게 정보 등록 API."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app

BODY = {"industry": "cafe", "address": "서울시 마포구 연남동 1-2", "name": "○○카페"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """실제 data/ 대신 임시 폴더에 저장하게 한다."""
    monkeypatch.setenv("ADS_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def test_등록하고_다시_조회한다(client: TestClient) -> None:
    """쿠키가 그대로 유지되므로 두 번째 요청이 같은 사장님으로 인식된다."""
    assert client.put("/store", json=BODY).status_code == 200
    got = client.get("/store")
    assert got.status_code == 200
    assert got.json()["industry"] == "cafe"


def test_처음_오면_404(client: TestClient) -> None:
    """등록 화면을 띄우라는 신호."""
    assert client.get("/store").status_code == 404


def test_등록하면_세션_쿠키를_준다(client: TestClient) -> None:
    res = client.put("/store", json=BODY)
    assert res.cookies.get("session_id")


def test_세션이_다르면_남의_정보가_보이지_않는다(client: TestClient) -> None:
    client.put("/store", json=BODY)
    client.cookies.clear()
    assert client.get("/store").status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        {"industry": "우주정거장", "address": "서울시 마포구 연남동"},
        {"industry": "cafe", "address": "부산광역시 해운대구"},
        {"industry": "cafe"},
    ],
)
def test_틀린_값은_422(client: TestClient, bad: dict) -> None:
    """모르는 업종 · 서울 밖 주소 · 주소 누락."""
    assert client.put("/store", json=bad).status_code == 422


def test_다시_등록하면_덮어쓴다(client: TestClient) -> None:
    client.put("/store", json=BODY)
    client.put("/store", json={**BODY, "industry": "restaurant"})
    assert client.get("/store").json()["industry"] == "restaurant"
