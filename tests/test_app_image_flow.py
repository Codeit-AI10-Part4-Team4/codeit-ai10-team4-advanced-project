"""이미지 흐름의 첫 계약 — 문구를 고르기 전엔 만들지 않고, 고른 문구가 그대로 전달된다.

`copies[0]` 자동 사용을 없앤 자리다 (docs/08 §3-2 규칙 5·6). 픽셀이 아니라
generate_ad 가 받은 인자를 spy 로 확인한다 — 이 흐름의 값어치는 "어느 문구로
만들었나"이므로.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from PIL import Image

from app_core.schema import AdBrief, CopyCandidate, Store

app = pytest.importorskip("app", reason="streamlit 미설치 환경에서는 건너뛴다")


class FakeState(dict):
    """st.session_state 대역 — 코드가 dict 식과 속성 식을 섞어 쓴다."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


@contextmanager
def _no_spinner(*a: Any, **kw: Any) -> Iterator[None]:
    yield


def _store() -> Store:
    return Store(id=1, user_id=1, industry="cafe", name="연남 크로플", address="서울시 마포구")


def _brief() -> AdBrief:
    return AdBrief(goal="image", product="크로플", price=4500)


def _install(monkeypatch: pytest.MonkeyPatch, state: FakeState) -> list[str]:
    """세션·스피너·안내 대역을 심고, info 로 그려진 문장을 모아 돌려준다."""
    infos: list[str] = []
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app.st, "spinner", _no_spinner)
    monkeypatch.setattr(app.st, "info", lambda msg, **kw: infos.append(str(msg)))
    return infos


def test_문구를_고르기_전에는_이미지를_만들지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    from app_core import pipeline

    calls: list[Any] = []
    monkeypatch.setattr(pipeline, "generate_ad", lambda *a, **kw: calls.append(a))
    infos = _install(monkeypatch, FakeState())

    assert app._make_images(_store(), _brief()) is False
    assert calls == []  # 비싼 생성이 시작조차 안 됐다
    assert any("골라주세요" in msg for msg in infos)


def test_고른_문구가_이미지_생성에_그대로_전달된다(monkeypatch: pytest.MonkeyPatch) -> None:
    from app_core import pipeline

    received: list[CopyCandidate] = []

    def _fake_generate(
        brief: AdBrief, store: Store, copy: CopyCandidate, style: str = "simple"
    ) -> Image.Image:
        received.append(copy)
        return Image.new("RGB", (8, 8))

    monkeypatch.setattr(pipeline, "generate_ad", _fake_generate)
    picked = CopyCandidate(id=7, headline="여름의 청량함", sub="6,000원")
    state = FakeState(picked=picked)
    _install(monkeypatch, state)

    assert app._make_images(_store(), _brief()) is True
    assert [c.id for c in received] == [7, 7]  # 감성형·포스터형 모두 고른 문구로
    assert set(state["images"]) == {"simple", "poster"}
