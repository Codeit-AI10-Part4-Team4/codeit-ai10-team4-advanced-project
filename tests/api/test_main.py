"""Smoke test proving the install/CI chain works end to end.

Convention: tests/ mirrors src/ (src/api/main.py -> tests/api/test_main.py).
"""

from fastapi.testclient import TestClient

from api.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
