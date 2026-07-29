"""FastAPI entrypoint.

Keep routers thin: request validation -> app_core call -> response mapping.
Business logic belongs in app_core, which must stay importable without FastAPI.
"""

from fastapi import FastAPI

app = FastAPI(title="my-ai-project")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe; replace with real routers as the project grows."""
    return {"status": "ok"}
