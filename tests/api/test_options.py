"""선택지 API — 화면 목록과 검증이 같은 곳에서 나오는지 확인한다."""

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


@pytest.mark.parametrize("kind", ["industries", "styles", "formats"])
def test_목록을_내려준다(kind: str) -> None:
    items = client.get(f"/options/{kind}").json()
    assert items
    assert all({"id", "label", "emoji"} == set(i) for i in items)


def test_프롬프트_필드는_내려보내지_않는다() -> None:
    """레지스트리 내부 필드가 새면 프론트가 그것에 의존하게 된다."""
    assert "scene_prompt" not in client.get("/options/industries").json()[0]


def test_없는_목록은_404() -> None:
    assert client.get("/options/색깔").status_code == 404


def test_선택지의_id는_그대로_등록에_쓸_수_있다(tmp_path, monkeypatch) -> None:
    """화면에 보인 선택지가 검증에서 거부되면 안 된다."""
    monkeypatch.setenv("ADS_DATA_DIR", str(tmp_path))
    with TestClient(app) as c:
        for item in c.get("/options/industries").json():
            body = {"industry": item["id"], "address": "서울시 마포구 연남동 1-2"}
            assert c.put("/store", json=body).status_code == 200
