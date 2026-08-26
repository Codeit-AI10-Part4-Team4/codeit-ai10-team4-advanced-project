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

from app_core.panel.review import Ranked
from app_core.panel.schemas import EvaluationResult, PersonaComment

app = pytest.importorskip("app", reason="streamlit 미설치 환경에서는 건너뛴다")


class Screen:
    """화면에 그려진 것을 종류별로 모은다."""

    def __init__(self) -> None:
        self.caption: list[str] = []
        self.info: list[str] = []
        self.success: list[str] = []
        self.warning: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> Screen:
        for kind in ("caption", "info", "success", "warning"):
            box = getattr(self, kind)
            monkeypatch.setattr(app.st, kind, lambda msg, box=box, **kw: box.append(str(msg)))
        return self

    @property
    def all_text(self) -> str:
        return "\n".join(self.caption + self.info + self.success + self.warning)


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


def _ranked(*intents: float) -> list[Ranked]:
    from app_core.schema import CopyCandidate

    return [
        Ranked(
            copy=CopyCandidate(headline=f"후보 {i}"),
            result=_result(scores={"attention": 60.0, "message": 70.0, "intent": intent}),
            defects=[],
        )
        for i, intent in enumerate(intents, start=1)
    ]


def test_격차가_확실하면_점수_대신_1위_추천을_보여준다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = Screen().install(monkeypatch)
    ranked = _ranked(54.0, 51.0, 49.0)

    app._rank_summary(ranked)

    assert "1위 문구" in "\n".join(screen.success)
    assert "점 차" not in screen.all_text
    assert "손님들이 가장 반응한 문구" in app._rank_caption(1, ranked)


def test_격차가_작으면_추천하지_않고_비슷하다고_알린다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = Screen().install(monkeypatch)
    ranked = _ranked(35.0, 34.0, 33.0)

    app._rank_summary(ranked)

    assert "셋이 비슷" in "\n".join(screen.info)
    assert not screen.success
    assert "가장 반응한" not in app._rank_caption(1, ranked)


def test_후보_카드에는_방문의향_절대_점수를_표시하지_않는다(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import nullcontext

    ranked = _ranked(54.0, 51.0, 49.0)
    screen = Screen().install(monkeypatch)
    store, _, _ = _args()
    draft: Any = object()
    monkeypatch.setattr(
        app.st,
        "session_state",
        _State(copies=[item.copy for item in ranked], ranked=ranked),
    )
    monkeypatch.setattr(app.st, "container", lambda **_kw: nullcontext())
    monkeypatch.setattr(app.st, "markdown", lambda *_a, **_kw: None)
    monkeypatch.setattr(app.st, "write", lambda *_a, **_kw: None)
    monkeypatch.setattr(app.st, "button", lambda *_a, **_kw: False)
    monkeypatch.setattr(app, "_panel_source", lambda *_a, **_kw: None)
    monkeypatch.setattr(app, "_rank_summary", lambda *_a, **_kw: None)
    monkeypatch.setattr(app, "revise_view", lambda *_a, **_kw: None)

    app.copy_view(store, draft)

    joined = "\n".join(screen.caption)
    assert "방문의향" not in joined
    assert all(str(score) not in joined for score in (54, 51, 49))
    assert "손님들이 가장 반응한 문구" in joined


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


def test_가격을_안_물어봤으면_그렇다고_말한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """ "가격 걸림돌 0명" 과 "가격을 안 물어봤음" 은 다르다.

    문구에 금액이 없으면 손님에게 객단가를 안 보여주고, 되묻고, 분류에도
    "price 는 고를 수 없다" 가 붙어서 `price` 가 **구조적으로** 0 이 된다.
    화면이 조용하면 사장님은 그 0 을 "가격은 문제없다" 로 읽는다.

    실측(2026-08-25, 같은 주문서 18,000원 · 문구만 교체):
    금액 있음 price 12/12 · 금액 없음 0/12. 그리고 금액 없음 쪽 손님들은
    "가격이 없어서 가볼 마음이 잘 안 생깁니다" 라고 답했다 — 가격이
    괜찮았던 게 아니라 **못 봤던** 것이다.
    """
    screen = Screen().install(monkeypatch)
    app._panel_source(_result(price_axis_closed=True, top_resistance=["message"]))
    joined = "\n".join(screen.info)
    assert "물어보지 않았습니다" in joined
    assert "금액을 넣고" in joined


def test_가격을_물어봤으면_그_말은_안_한다(monkeypatch: pytest.MonkeyPatch) -> None:
    """문구에 금액이 있으면 이 배지는 안 뜬다 — 뜨면 거짓말이다."""
    screen = Screen().install(monkeypatch)
    app._panel_source(_result())
    assert not screen.info


def test_가격_배지는_신뢰도와_무관하다(monkeypatch: pytest.MonkeyPatch) -> None:
    """축 하나를 안 쓴 것이지 평가가 부실한 게 아니다.

    사유 목록(`confidence_reasons`)에 넣으면 `confidence` 가 같이 "low" 로
    떨어진다 — 그 목록의 뜻은 **"이 평가를 믿기 어렵다"** 이고, 여기는
    그 뜻이 아니다. `is_category_fallback` 과 같은 층의 플래그로 둔 이유다.
    """
    screen = Screen().install(monkeypatch)
    app._panel_source(_result(price_axis_closed=True))
    assert not screen.warning


def test_주소를_못_찾아도_가격_배지는_따로_뜬다(monkeypatch: pytest.MonkeyPatch) -> None:
    """폴백 두 개는 센 쪽 하나만 말하지만, 가격 축은 다른 얘기다.

    "어느 동네 손님인가" 와 "가격을 물어봤는가" 는 겹치지 않는다. 한쪽이
    켜졌다고 다른 쪽을 숨기면 사장님이 못 듣는 사실이 생긴다.
    """
    screen = Screen().install(monkeypatch)
    app._panel_source(_result(is_fallback=True, price_axis_closed=True))
    assert "서울 평균" in "\n".join(screen.warning)
    assert "물어보지 않았습니다" in "\n".join(screen.info)


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
