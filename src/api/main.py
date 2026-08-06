"""FastAPI entrypoint.

Keep routers thin: request validation -> app_core call -> response mapping.
Business logic belongs in app_core, which must stay importable without FastAPI.
"""

from fastapi import FastAPI

from api.routers import options, store

app = FastAPI(title="codeit-ai10-team4-advanced-project")

app.include_router(store.router)
app.include_router(options.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe; replace with real routers as the project grows."""
    return {"status": "ok"}
