"""build_panel 검증 — 축 값이 데이터에서 나오는지.

DuckDB 없이도 도는 테스트가 대부분이다(피처 딕셔너리를 직접 만들어 넣는다).
실제 상권으로 도는 테스트만 DB 를 요구한다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app_core.panel.features import DB_PATH, build_features
from app_core.panel.panel_builder import (
    WORK_RATIO_HIGH,
    boundary_age,
    build_panel,
    motive,
    price_sens,
)

YEOKSAM = (127.0365, 37.5005)


def _features(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "area_nm": "테스트상권",
        "category_nm": "커피-음료",
        "gender_share": {"M": 0.5, "F": 0.5},
        "age_share": {"10": 0.02, "20": 0.18, "30": 0.4, "40": 0.2, "50": 0.13, "60": 0.07},
        "foot_age_share": {"10": 0.08, "20": 0.3, "30": 0.3, "40": 0.16, "50": 0.1, "60": 0.06},
        "time_share": {
            "00-06": 0.01,
            "06-11": 0.15,
            "11-14": 0.45,
            "14-17": 0.19,
            "17-21": 0.18,
            "21-24": 0.02,
        },
        "avg_ticket": 9000,
        "avg_ticket_pct": 0.5,
        "work_ratio": 0.9,
        "apt_avg_price": None,
    }
    return {**base, **over}


def test_페르소나는_성별x연령_12개다() -> None:
    ps = build_panel(_features())
    assert len(ps) == 12
    assert len({p["demo"] for p in ps}) == 12
    assert sum(p["weight"] for p in ps) == pytest.approx(1.0, abs=0.01)


def test_가중치는_두_축의_곱이다() -> None:
    f = _features()
    for p in build_panel(f):
        age = p["demo"][:2]
        g = "M" if "남성" in p["demo"] else "F"
        expected = f["gender_share"][g] * f["age_share"][age]
        assert p["weight"] == pytest.approx(expected, abs=1e-3), p["demo"]


def test_객단가_분위가_가격_저항을_정한다() -> None:
    assert price_sens(_features(avg_ticket_pct=0.9)) == "low"  # 비싼 동네 = 저항 낮음
    assert price_sens(_features(avg_ticket_pct=0.5)) == "mid"
    assert price_sens(_features(avg_ticket_pct=0.1)) == "high"


def test_비싼_아파트가_배후면_가격_저항이_한_단계_완화된다() -> None:
    assert price_sens(_features(avg_ticket_pct=0.1)) == "high"
    assert price_sens(_features(avg_ticket_pct=0.1, apt_avg_price=1_500_000_000)) == "mid"


def test_출퇴근_상권은_반복_방문이_기본이다() -> None:
    assert motive(_features(work_ratio=WORK_RATIO_HIGH + 0.1)) == "habitual"
    assert motive(_features(work_ratio=WORK_RATIO_HIGH - 0.2)) == "exploratory"


def test_인구_데이터가_없으면_시간대_집중도로_대신한다() -> None:
    # work_ratio 가 None 이어도 죽지 않는다 (CSV 3종을 안 받은 상태)
    assert motive(_features(work_ratio=None)) == "habitual"


def test_경계는_유동_대비_매출이_가장_낮은_층이다() -> None:
    # 20대: 매출 0.18 / 유동 0.30 = 0.60 이 가장 낮다
    assert boundary_age(_features()) == "20"


def test_비중이_너무_작은_층은_경계로_뽑지_않는다() -> None:
    # 10대는 비율(0.02/0.08=0.25)이 더 낮지만 매출 비중 2%라 가중치 기여가 없다
    assert boundary_age(_features()) != "10"


def test_시간대는_매출_분포를_닮게_배분된다() -> None:
    ps = build_panel(_features())
    lunch = sum(p["weight"] for p in ps if p["axes"]["time"] == "weekday_lunch")
    # 매출의 45%가 점심 → 페르소나 가중치도 그 언저리
    assert 0.3 < lunch < 0.6
    assert len({p["axes"]["time"] for p in ps}) >= 3


def test_근거는_실제_피처값과_일치한다() -> None:
    f = _features()
    for p in build_panel(f):
        for e in p["evidence"]:
            head, _, key = e["path"].partition(".")
            assert f[head][key] == e["value"], e["path"]


def test_서사를_외부에_위임할_수_있다() -> None:
    called: list[int] = []

    def narrator(personas: list[dict[str, Any]], features: dict[str, Any]) -> list[str]:
        called.append(len(personas))
        return [f"{p['demo']} 이야기" for p in personas]

    ps = build_panel(_features(), narrator=narrator)
    assert called == [12]  # 배치 1콜
    assert all(p["narrative"].endswith("이야기") for p in ps)


@pytest.mark.skipif(not DB_PATH.exists(), reason="data/panel.duckdb 없음")
def test_상권_성격이_다르면_패널도_달라진다() -> None:
    office = build_panel(build_features("", "cafe", coord=YEOKSAM))
    hongdae = build_panel(build_features("", "korean_food", coord=(126.9250, 37.5610)))
    assert office[0]["axes"]["motive"] == "habitual"  # 역삼 work_ratio 0.94
    assert hongdae[0]["axes"]["motive"] == "exploratory"  # 홍대 0.52
