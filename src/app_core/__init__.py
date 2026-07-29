"""Domain logic package.

Dependency rule: api -> app_core (one way). Never import `api` from here —
app_core must run and test standalone, without FastAPI.
"""

__all__: list[str] = []
