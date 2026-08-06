"""FastAPI entrypoint.

지금은 헬스체크만 있다. 프론트를 React 로 바꿀 때 여기에 라우터를 붙인다 —
로직은 app_core 에 있으므로 라우터는 얇게(요청 검증 → app_core 호출 → 응답 변환).
"""

from fastapi import FastAPI

app = FastAPI(title="codeit-ai10-team4-advanced-project")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
