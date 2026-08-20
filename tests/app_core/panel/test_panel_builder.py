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
    WeightError,
    adjust_weights,
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
        "back_age_share": None,
        "apt_avg_price": None,
    }
    return {**base, **over}


def test_페르소나는_성별x연령_12개다() -> None:
    ps = build_panel(_features())
    assert len(ps) == 12
    assert len({p["demo"] for p in ps}) == 12
    assert sum(p["weight"] for p in ps) == pytest.approx(1.0, abs=0.01)


def test_매출이_0_인_연령대는_페르소나를_안_만든다() -> None:
    """`Persona.weight` 는 `gt=0.0` 이라 가중치 0 이면 패널이 통째로 터진다.

    실측(2026-08-19) — 랜덤 상권 9곳에 관통을 돌리자 4곳이 여기서 죽었다.
    난우중학교 미용실은 20대 매출이 0원, 동평화시장 한식은 10대가 0원이었다.
    주소 × 업종 50,016 조합 중 10,448 (20.9%) 이 해당한다.

    좌표를 박아둔 역삼·홍대·수유에서만 돌리는 동안은 한 번도 안 보였다 —
    그 셋은 전 연령대에 매출이 있다.
    """
    f = _features(age_share={"10": 0.0, "20": 0.2, "30": 0.4, "40": 0.2, "50": 0.13, "60": 0.07})
    ps = build_panel(f)

    assert len(ps) == 10, "10대 남녀 둘이 빠져야 한다"
    assert all(p["weight"] > 0 for p in ps)
    assert "10대" not in {p["demo"].split()[0] for p in ps}
    # 뺀 항이 0 이라 합은 그대로다 — `Panel._check_personas` 가 이걸 본다.
    assert sum(p["weight"] for p in ps) == pytest.approx(1.0, abs=0.01)
    assert len({p["persona_id"] for p in ps}) == 10, "id 가 안 겹쳐야 한다"


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


def test_나이대_객단가가_가격_저항을_한_칸_옮긴다() -> None:
    """상권 값 하나만 쓰면 12명이 같은 숫자와 견주게 되어 답이 하나로 모인다.

    실측(2026-08-12): 손님 12명 중 10명이 걸림돌로 price 를 골랐고, 그중 5명은
    코멘트가 글자 하나 안 틀리고 같았다.
    """
    f = _features(
        avg_ticket_pct=0.5,  # 상권 기준은 mid
        age_ticket={"10": 6000, "30": 8300, "60": 10500},
        age_ticket_base=8300,
    )
    assert price_sens(f, "10") == "high"  # 0.72 — 또래보다 적게 쓴다
    assert price_sens(f, "30") == "mid"  # 1.00
    assert price_sens(f, "60") == "low"  # 1.27
    assert price_sens(f) == "mid"  # 나이를 안 주면 상권 값 그대로


def test_가격_저항은_양끝을_넘지_않는다() -> None:
    f = _features(avg_ticket_pct=0.9, age_ticket={"60": 10500}, age_ticket_base=8300)
    assert price_sens(f, "60") == "low"  # 이미 low 인데 더 올라가지 않는다


def test_건수가_적은_나이대는_상권_값으로_돌아간다() -> None:
    """역삼 치킨 10대는 결제 14건으로 92,005원이 나온다 — 그 업종 전체의 1.5배다.

    `MIN_SALES_CNT` 미달이면 `age_ticket` 이 None 이고, 그러면 보정하지 않는다.
    """
    f = _features(avg_ticket_pct=0.5, age_ticket={"10": None, "30": 8300}, age_ticket_base=8300)
    assert price_sens(f, "10") == "mid"


def test_패널은_나이대별로_다른_가격_저항을_준다() -> None:
    f = _features(
        age_ticket={"10": 6000, "20": 7800, "30": 8300, "40": 8600, "50": 9000, "60": 10500},
        age_ticket_base=8300,
    )
    levels = {p["axes"]["price_sens"] for p in build_panel(f)}
    assert len(levels) >= 2, "12명이 가격에 대해 한 덩어리로 답한다"
    # motive 는 아직 상권 단위다 — 나이대로 쪼갤 실측 근거가 없다
    assert len({p["axes"]["motive"] for p in build_panel(f)}) == 1


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


def test_배후지_구성도_경계_판정에_쓰인다() -> None:
    """동네 주민(배후지)에 많은데 안 사는 층도 경계다 (07 §4.4⑩)."""
    # 유동인구로만 보면 60대(0.07/0.06=1.17)가 낮지 않지만,
    # 배후지에 60대가 20%나 사는데 매출은 7%뿐이라면 놓치고 있는 층이다.
    f = _features(
        foot_age_share={"10": 0.08, "20": 0.2, "30": 0.3, "40": 0.2, "50": 0.16, "60": 0.06},
        back_age_share={"10": 0.02, "20": 0.15, "30": 0.25, "40": 0.2, "50": 0.18, "60": 0.20},
    )
    assert boundary_age(f) == "60"


def test_배후지가_없어도_동작한다() -> None:
    """발달상권·전통시장·관광특구에는 배후지 데이터가 없다 (전체의 34%)."""
    assert boundary_age(_features(back_age_share=None)) == "20"


def test_고친_비중은_그대로_쓰고_나머지가_남은_몫을_나눈다() -> None:
    ps = build_panel(_features())
    before = {p["persona_id"]: p["weight"] for p in ps}
    target = ps[0]["persona_id"]

    out = adjust_weights(ps, {target: 0.5})
    got = {p["persona_id"]: p["weight"] for p in out}

    assert got[target] == 0.5
    assert sum(got.values()) == pytest.approx(1.0, abs=0.01)
    # 손대지 않은 둘 사이의 상대 관계는 그대로다
    a, b = ps[1]["persona_id"], ps[2]["persona_id"]
    assert got[a] / got[b] == pytest.approx(before[a] / before[b], rel=0.01)


def test_조정한_손님에_표시가_남는다() -> None:
    ps = build_panel(_features())
    out = adjust_weights(ps, {ps[0]["persona_id"]: 0.3})
    assert out[0]["is_adjusted"] is True
    assert out[1]["is_adjusted"] is False


def test_말이_안_되는_비중은_사장님_언어로_막는다() -> None:
    ps = build_panel(_features())
    with pytest.raises(WeightError, match="모르는 손님"):
        adjust_weights(ps, {"p99": 0.5})
    with pytest.raises(WeightError, match="0보다 작을 수 없습니다"):
        adjust_weights(ps, {ps[0]["persona_id"]: -0.1})
    with pytest.raises(WeightError, match="100%를 넘습니다"):
        adjust_weights(ps, {p["persona_id"]: 0.5 for p in ps[:3]})


def test_조정하지_않으면_그대로다() -> None:
    ps = build_panel(_features())
    assert adjust_weights(ps, {}) == ps


def test_골든_픽스처가_지금_코드가_만드는_패널과_같다(yeoksam_raw: dict[str, Any]) -> None:
    """픽스처가 코드보다 낡으면 **그 픽스처로 잰 모든 것이 과거를 잰다.**

    2026-08-20 실측: `price_sens` 나이 보정이 코드에만 들어가고 픽스처에는
    반영되지 않아, 12명이 전원 `mid` 인 패널로 평가·A/B·라벨 검사를 돌리고
    있었다. 실제 앱은 DuckDB 로 매번 새로 만들므로 `high 2 · mid 8 · low 2`
    를 쓴다 — **평가와 제품이 다른 패널을 보고 있었다.**

    `weight`·`narrative`·`evidence` 는 12명 다 맞아서 테스트 688 개가 전부
    통과했다. 픽스처를 정답으로 삼는 테스트는 이 어긋남을 구조적으로 못 본다.
    그래서 **픽스처를 코드와 대조하는** 검사가 따로 필요하다.

    DB 를 안 쓴다 — 픽스처 자신의 `features` 로 다시 만들어 견준다.
    """
    rebuilt = {p["demo"]: p for p in build_panel(yeoksam_raw["features"])}
    stale = [
        f"{p['demo']}: {p['axes']} → {rebuilt[p['demo']]['axes']}"
        for p in yeoksam_raw["personas"]
        if p != rebuilt[p["demo"]]
    ]
    assert not stale, (
        "골든 픽스처가 코드와 어긋난다 — personas 를 build_panel(features) 로 "
        "다시 만들어 넣어야 한다: " + " / ".join(stale)
    )
