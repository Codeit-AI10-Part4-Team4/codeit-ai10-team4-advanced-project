"""화면이 **무엇을 근거로 한 평가인지** 말하는지 본다.

집계 결과는 신뢰도 필드를 아홉 개 실어 보내는데 화면은 오래도록 `scores` ·
`suggestions` · `top_resistance` 셋만 썼다. `schemas.py` 가 "결과 화면에 배지를
띄운다"고 적어둔 배지가 없었고, 화면 코드에 테스트가 하나도 없어서 아무도 못 봤다.

`app.py` 는 streamlit 스크립트라 import 하면 화면이 통째로 돌았는데, `main()` 에
`__name__` 가드를 두면서 import 가 가능해졌다. 여기가 그 첫 테스트다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel.schemas import EvaluationResult, PersonaComment

app = pytest.importorskip("app", reason="streamlit 미설치 환경에서는 건너뛴다")


class Screen:
    """화면에 그려진 것을 종류별로 모은다."""

    def __init__(self) -> None:
        self.caption: list[str] = []
        self.info: list[str] = []
        self.warning: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> Screen:
        for kind in ("caption", "info", "warning"):
            box = getattr(self, kind)
            monkeypatch.setattr(app.st, kind, lambda msg, box=box, **kw: box.append(str(msg)))
        return self

    @property
    def all_text(self) -> str:
        return "\n".join(self.caption + self.info + self.warning)


def _result(survivors: int = 12, **over: Any) -> EvaluationResult:
    base: dict[str, Any] = {
        "ad_id": "x",
        "scores": {"attention": 60.0, "message": 70.0, "intent": 52.0},
        "confidence": "ok",
        "confidence_reasons": [],
        "max_metric_std": 1.0,
        "top_resistance": ["price"],
        "persona_comments": [
            PersonaComment(
                persona_id=f"p{i:02d}",
                demo="30대 여성",
                weight=0.08,
                is_boundary=False,
                resistance="price",
                comment="c",
            )
            for i in range(survivors)
        ],
        "area_nm": "역삼역",
        "quarter": "20261",
        "is_fallback": False,
        "is_category_fallback": False,
        "demo_coverage": 0.9,
        "excluded_cnt": 0,
    }
    base.update(over)
    return EvaluationResult(**base)


def test_어느_동네_언제_데이터인지_밝힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "동네 손님 12명"이라고 말하려면 어느 동네인지도 말해야 한다."""
    screen = Screen().install(monkeypatch)
    app._panel_source(_result())
    assert "역삼역" in screen.all_text
    assert "2026년 1분기" in screen.all_text
    assert "12명" in screen.all_text


def test_업종_폴백이면_전체_손님_기준이라고_말한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """폴백이면 객단가가 통째로 바뀐다 — 실측: 관악 분식이 9,546원대가 아니라 40,141원.

    화면이 조용하면 사장님은 자기 업종 손님이 본 줄 안다.
    """
    screen = Screen().install(monkeypatch)
    app._panel_source(_result(is_category_fallback=True))
    assert "동네 전체 손님 기준" in "\n".join(screen.info)


def test_주소를_못_찾았으면_서울_평균이라고_경고한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """업종 폴백보다 센 경고다 — "우리 동네"라는 그라운딩 자체가 없다."""
    screen = Screen().install(monkeypatch)
    app._panel_source(_result(is_fallback=True, is_category_fallback=True))
    assert "서울 평균" in "\n".join(screen.warning)
    assert not screen.info  # 둘 다 켜져 있어도 센 쪽 하나만 말한다


def test_탈락한_손님이_있으면_그_수를_밝힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    """9명이 답했는데 화면이 "12명"이라고만 하면 그건 사실이 아니다."""
    screen = Screen().install(monkeypatch)
    app._panel_source(_result(survivors=9, excluded_cnt=3))
    text = screen.all_text
    assert "12명" in text  # 물어본 사람은 12명이 맞다
    assert "3명은 빼고" in text  # 다만 셋은 안 셌다


def test_신뢰도가_낮으면_이유까지_보여준다(monkeypatch: pytest.MonkeyPatch) -> None:
    """사유는 집계가 사람 문장으로 만들어 준다 — 화면은 그대로 옮기기만 한다."""
    screen = Screen().install(monkeypatch)
    app._panel_source(
        _result(
            confidence="low",
            confidence_reasons=["한 손님의 비중이 41%라 결과가 그쪽으로 쏠림"],
        )
    )
    joined = "\n".join(screen.warning)
    assert "참고만" in joined
    assert "41%" in joined


def test_정상이면_경고를_띄우지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """다 정상인데 배지가 뜨면 배지가 의미를 잃는다."""
    screen = Screen().install(monkeypatch)
    app._panel_source(_result())
    assert not screen.warning
    assert not screen.info


# ── 실패했을 때 안내가 남는가 ──────────────────────────────────────
#
# 귀한님이 통합 스모크에서 찾은 것(2026-08-19): 카카오 키가 없는 환경에서
# "동네 손님 12명에게 셋 다 보여주기"를 눌러도 **아무 일도 안 일어났다.**
# `_rank_copies` 가 안내문을 띄우는데 부르는 쪽이 성공 여부와 상관없이
# `st.rerun()` 을 돌려 그 자리에서 지워버렸다.
#
# `_make_copies` 는 #20 에서 같은 이유로 이미 bool 이었다. 바로 아래 버튼만
# 안 고쳐져 있었고, 두 줄 위 주석에 "실패했을 때는 그대로 둬야 에러 문구가
# 남는다"고 적혀 있었는데도 그랬다 — 주석은 규칙을 지켜주지 않는다.


class _State(dict):
    """`st.session_state` 흉내. 속성으로도 키로도 읽고 쓴다."""

    def __getattr__(self, k: str) -> Any:
        return self[k]

    def __setattr__(self, k: str, v: Any) -> None:
        self[k] = v


def _stub_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """`spinner`·`expander` 는 with 문에 쓰이므로 컨텍스트 매니저로 바꾼다."""
    from contextlib import nullcontext

    for name in ("spinner", "expander"):
        monkeypatch.setattr(app.st, name, lambda *a, **k: nullcontext())
    monkeypatch.setattr(app.st, "code", lambda *a, **k: None)
    monkeypatch.setattr(app.st, "session_state", _State())


def _args() -> tuple[Any, Any, list[Any]]:
    from app_core.schema import AdBrief, CopyCandidate, Store, StoreInput

    base = StoreInput(industry="cafe", name="테스트카페", address="서울 강남구 테헤란로 152")
    return (
        Store(**base.model_dump(), id=1, user_id=1),
        AdBrief(goal="copy", product="크로플", price=6000, situation="신메뉴"),
        [CopyCandidate(headline="점심 후 달달한 크로플", sub="6,000원")],
    )


def test_동네를_못_찾으면_False_를_돌려주고_안내를_남긴다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """False 를 못 돌려주면 부르는 쪽이 rerun 해서 이 안내가 사라진다."""
    from app_core.panel.features import NoTradeAreaError

    def _raise(*_a: Any, **_k: Any) -> None:
        raise NoTradeAreaError("KAKAO_REST_KEY 가 없습니다. coord 를 직접 넘기세요.")

    screen = Screen().install(monkeypatch)
    _stub_layout(monkeypatch)
    monkeypatch.setattr(app, "rank", _raise)

    assert app._rank_copies(*_args()) is False
    joined = "\n".join(screen.warning)
    assert "동네 손님을 불러오지 못했습니다" in joined
    # 개발자 문장이 사장님 화면 본문에 그대로 뜨면 안 된다 — 접어서 보여준다.
    assert "KAKAO_REST_KEY" not in joined


def test_성공하면_True_를_돌려준다(monkeypatch: pytest.MonkeyPatch) -> None:
    """성공했을 때만 rerun 해야 방금 만든 순위가 화면에 나온다."""
    screen = Screen().install(monkeypatch)
    _stub_layout(monkeypatch)
    monkeypatch.setattr(app, "rank", lambda *a, **k: ["순위결과"])

    assert app._rank_copies(*_args()) is True
    assert app.st.session_state["ranked"] == ["순위결과"]
    assert not screen.warning
