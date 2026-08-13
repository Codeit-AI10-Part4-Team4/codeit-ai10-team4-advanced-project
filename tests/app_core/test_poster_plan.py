"""기획 부품 테스트 — LLM 을 대역으로 바꿔 실제 호출 없이 검증한다 (팀 규칙)."""

import json

import pytest

from app_core import poster_plan


class _FakeCompletions:
    def __init__(self, payload: str):
        self._payload = payload

    def create(self, **kwargs):
        msg = type("M", (), {"content": self._payload})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


def _fake_openai(payload: dict):
    text = json.dumps(payload, ensure_ascii=False)

    class _Fake:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": _FakeCompletions(text)})()

    return _Fake


def test_plan_poster_parses_fields(monkeypatch):
    monkeypatch.setattr(
        "openai.OpenAI",
        _fake_openai(
            {
                "tagline": "봄과 함께",
                "badge": "봄 시즌",
                "date_line": "3월",
                "features": [
                    "다채로운 꽃|고르는 즐거움",
                    "정성 포장|선물하기 좋게",
                    "관리 안내|오래가는 법",
                ],
                "event": "3월 한 달 할인",
                "palette": "soft_pink",
            }
        ),
    )
    plan = poster_plan.plan_poster("연남 플라워", "꽃집", "봄 꽃다발")
    assert plan.badge == "봄 시즌"
    assert len(plan.features) == 3
    assert plan.palette in poster_plan.PALETTES


def test_plan_poster_allows_empty_event(monkeypatch):
    """말하지 않은 이벤트·날짜는 비어 있어야 한다 — 지어내면 허위광고가 된다."""
    monkeypatch.setattr(
        "openai.OpenAI",
        _fake_openai(
            {
                "tagline": "동네 꽃집",
                "badge": "신규 오픈",
                "date_line": "",
                "features": ["a|b", "c|d", "e|f"],
                "event": "",
                "palette": "fresh_mint",
            }
        ),
    )
    plan = poster_plan.plan_poster("연남 플라워", "꽃집", "꽃다발")
    assert plan.date_line == ""
    assert plan.event == ""


def test_unknown_palette_is_rejected(monkeypatch):
    """모르는 팔레트 이름이 오면 그리기 전에 걸러야 한다."""
    monkeypatch.setattr(
        "openai.OpenAI",
        _fake_openai(
            {
                "tagline": "x",
                "badge": "y",
                "date_line": "",
                "features": ["a|b"],
                "event": "",
                "palette": "노랑무지개",
            }
        ),
    )
    with pytest.raises(ValueError):
        poster_plan.plan_poster("가게", "꽃집", "꽃")
