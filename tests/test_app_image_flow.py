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
    monkeypatch.setattr(pipeline, "prepare_output", lambda *a, **kw: calls.append(a))
    infos = _install(monkeypatch, FakeState(output_type="emotional_text"))

    assert app._make_images(_store(), _brief()) is False
    assert calls == []  # 비싼 생성이 시작조차 안 됐다
    assert any("골라주세요" in msg for msg in infos)


def test_글자_없는_유형은_문구_없이도_만든다(monkeypatch: pytest.MonkeyPatch) -> None:
    """문구를 고르는 화면 자체를 안 거치는 유형이다 — 여기서 막으면 영영 못 만든다."""
    from app_core import pipeline

    monkeypatch.setattr(pipeline, "prepare_output", lambda brief, store, out: f"MAT-{out}")
    received: list[Any] = []

    def _fake_render(materials: Any, output_type: str, copy: Any) -> Image.Image:
        received.append((materials, output_type, copy))
        return Image.new("RGB", (8, 8))

    monkeypatch.setattr(pipeline, "render_output", _fake_render)
    state = FakeState(output_type="emotional_no_text")
    _install(monkeypatch, state)

    assert app._make_images(_store(), _brief()) is True
    assert received == [("MAT-emotional_no_text", "emotional_no_text", None)]


def test_고른_문구가_이미지_생성에_그대로_전달된다(monkeypatch: pytest.MonkeyPatch) -> None:
    from app_core import pipeline

    received: list[tuple[Any, int | None]] = []
    monkeypatch.setattr(pipeline, "prepare_output", lambda brief, store, out: f"MAT-{out}")

    def _fake_render(materials: Any, output_type: str, copy: CopyCandidate) -> Image.Image:
        received.append((materials, copy.id))
        return Image.new("RGB", (8, 8))

    monkeypatch.setattr(pipeline, "render_output", _fake_render)
    picked = CopyCandidate(id=7, headline="여름의 청량함", sub="6,000원")
    state = FakeState(picked=picked, output_type="poster")
    _install(monkeypatch, state)

    assert app._make_images(_store(), _brief()) is True
    # 고른 **한 형태만** 만든다 — 안 고른 쪽에 GPU·API 비용이 나가면 안 된다
    assert received == [("MAT-poster", 7)]
    assert set(state["images"]) == {"poster"}


def test_문구만_바꾸면_재료를_다시_만들지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2 의 존재 이유 — 재료가 있고 주문서가 같으면 비싼 단계는 0회다 (docs/08 §4-1)."""
    from app_core import pipeline

    prepare_calls: list[Any] = []
    monkeypatch.setattr(pipeline, "prepare_output", lambda *a, **kw: prepare_calls.append(a))
    monkeypatch.setattr(pipeline, "render_output", lambda m, o, c: Image.new("RGB", (8, 8)))
    state = FakeState(
        picked=CopyCandidate(id=1, headline="다른 문구"),
        output_type="emotional_text",
        materials={"emotional_text": "MAT"},
        materials_brief=_brief(),
        mat_errors={},
    )
    _install(monkeypatch, state)

    assert app._make_images(_store(), _brief()) is True
    assert prepare_calls == []  # 재료 재사용 — 배경 생성·기획이 다시 돌지 않았다


def test_다운로드_파일명_날짜는_한국_시간으로_찍는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """UTC 로 찍으면 한국 오전 9시 전에 만든 광고가 전날 파일명이 된다 — #47 리뷰(아인님)."""
    from datetime import datetime as real_datetime
    from zoneinfo import ZoneInfo

    from PIL import Image

    from app_core.schema import Store, StoreInput

    asked: dict[str, Any] = {}

    class _FakeDatetime:
        @staticmethod
        def now(tz: Any = None) -> Any:
            asked["tz"] = tz
            return real_datetime(2026, 8, 21, 0, 30, tzinfo=tz)

    class _Col:
        def button(self, *a: Any, **kw: Any) -> bool:
            return False

        def download_button(self, *a: Any, **kw: Any) -> None:
            asked["file_name"] = kw["file_name"]

    monkeypatch.setattr(app.st, "session_state", FakeState())
    monkeypatch.setattr(app.st, "columns", lambda n: (_Col(), _Col()))
    monkeypatch.setattr(app, "datetime", _FakeDatetime)

    base = StoreInput(industry="cafe", name="테스트카페", address="서울 강남구 테헤란로 152")
    store = Store(**base.model_dump(), id=1, user_id=1)
    app._save_and_download(store, "크로플", "simple", "감성 피드형", Image.new("RGB", (1, 1)))

    assert asked["tz"] == ZoneInfo("Asia/Seoul")  # 서울 시간으로 물었는가 — 이게 계약
    assert "20260821" in asked["file_name"]
