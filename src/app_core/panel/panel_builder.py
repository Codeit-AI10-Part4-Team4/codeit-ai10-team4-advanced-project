"""상권 피처 → 가상 손님 패널.

`build_features()` 결과를 받아 페르소나 12개(성별 2 × 연령 6)를 만든다.
**축 값·가중치는 전부 코드가 정하고, LLM 은 서사 한 문장만 쓴다** (07 §7.1).

축을 어떤 근거로 정하는지가 이 파일의 전부다. 근거 없는 다양성은 만들지 않는다.

  price_sens  상권 객단가 분위 + 배후 아파트 시가   → 상권 단위 (전원 동일)
  motive      work_ratio (출퇴근 상권인가)          → 상권 단위 (전원 동일)
  time        매출 시간대 분포에 맞춰 배분          → 페르소나마다 다름
  weight      gender_share × age_share             → 두 축의 곱

**price_sens·motive 가 전원 동일한 것은 의도한 것이다.** 상권 단위로만 관측되는
값이라, 연령별로 다르게 주려면 계수를 지어내야 한다. 지어낸 다양성은 코멘트를
그럴듯하게 만들 뿐 근거를 늘리지 않는다 (07 §4.6). 시간대만 페르소나별로 다른
이유는 매출 시간대 분포라는 실측 근거가 있기 때문이다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

#: 매출 비중이 이 값 미만인 연령대는 경계 페르소나로 뽑지 않는다.
#: 비중이 0에 가까우면 가중치도 0이라 코멘트 한 줄 외에 기여가 없다.
BOUNDARY_MIN_SHARE: Final = 0.03

#: 출퇴근 상권으로 보는 기준. 역삼역 0.94 / 홍대입구 0.52 로 갈린다.
WORK_RATIO_HIGH: Final = 0.7

#: 아파트 평균 시가가 이 값을 넘으면 가격 저항을 한 단계 낮춘다(원).
APT_PRICE_HIGH: Final = 800_000_000

TIME_LABEL: Final = {
    "00-06": "night",
    "06-11": "morning",
    "11-14": "weekday_lunch",
    "14-17": "afternoon",
    "17-21": "evening",
    "21-24": "night",
}

#: 서사에 넣을 사람 말. 축 값은 영어 id 라 그대로 문장에 넣으면 어색하다.
TIME_KO: Final = {
    "morning": "아침",
    "weekday_lunch": "점심",
    "afternoon": "오후",
    "evening": "저녁",
    "night": "늦은 시간",
}

AGE_LABEL: Final = {
    "10": "10대",
    "20": "20대",
    "30": "30대",
    "40": "40대",
    "50": "50대",
    "60": "60대",
}


def price_sens(features: dict[str, Any]) -> str:
    """상권의 가격 저항. 객단가 분위가 기준이고 배후 아파트 시가로 한 번 보정한다.

    객단가가 높다 = 그 동네 손님이 그 값을 내고 있다 = 가격 저항이 낮다.
    """
    pct = features.get("avg_ticket_pct", 0.5)
    level = "low" if pct > 0.75 else "high" if pct < 0.25 else "mid"
    apt = features.get("apt_avg_price")
    if apt and apt > APT_PRICE_HIGH and level != "low":
        # 비싼 아파트가 배후면 소득이 받쳐준다 — 한 단계 완화
        level = "mid" if level == "high" else "low"
    return level


def motive(features: dict[str, Any]) -> str:
    """방문 동기. 출퇴근 상권은 반복 방문(habitual)이 기본이다."""
    ratio = features.get("work_ratio")
    if ratio is None:
        # 인구 데이터가 없으면 시간대 집중도로 대신한다 (구 방식)
        return "habitual" if max(features["time_share"].values()) > 0.35 else "exploratory"
    return "habitual" if ratio >= WORK_RATIO_HIGH else "exploratory"


def _assign_times(weights: list[float], time_share: dict[str, float]) -> list[str]:
    """페르소나에 시간대를 배분한다.

    **패널의 시간대 분포가 매출 시간대 분포를 닮게** 만든다 — 매출의 48%가
    점심이면 페르소나 가중치의 절반쯤이 점심을 맡는다. 무거운 페르소나부터
    큰 시간대에 배정한다.
    """
    bands = sorted(time_share.items(), key=lambda kv: -kv[1])
    order = sorted(range(len(weights)), key=lambda i: -weights[i])
    out = [""] * len(weights)
    bi, filled = 0, 0.0
    for i in order:
        band, share = bands[bi]
        out[i] = TIME_LABEL[band]
        filled += weights[i]
        # 이 시간대 몫을 채웠으면 다음 시간대로. 마지막 밴드는 남은 전부를 받는다.
        if filled >= share and bi < len(bands) - 1:
            bi += 1
            filled = 0.0
    return out


def boundary_age(features: dict[str, Any]) -> str | None:
    """잠재 고객 풀에 비해 실제로 사지 않는 연령대. 경계 페르소나가 될 층이다.

    잠재 풀은 두 가지로 관측된다.
      · `foot_age_share`  지나다니는 사람 (도달)
      · `back_age_share`  배후지 = 동네 주민 (거주). 골목상권에만 있다.

    둘 중 **큰 쪽**을 분모로 쓴다 — 어느 경로로든 닿을 수 있었는데 안 산 층을
    잡기 위해서다. 비중이 너무 작으면(역삼역 10대 0.35%) 가중치 기여가 없어
    코멘트 한 줄 외에 의미가 없으므로 제외한다.
    """
    age = features["age_share"]
    foot = features.get("foot_age_share") or {}
    back = features.get("back_age_share") or {}
    ratios = {}
    for a, share in age.items():
        if share < BOUNDARY_MIN_SHARE:
            continue
        pool = max(foot.get(a, 0.0), back.get(a, 0.0))
        if pool > 0:
            ratios[a] = share / pool
    return min(ratios, key=lambda a: ratios[a]) if ratios else None


def stub_narrative(persona: dict[str, Any], features: dict[str, Any]) -> str:
    """LLM 없이 쓰는 사실 나열. 키가 없거나 모델이 답을 빠뜨려도 패널이 돌게 한다."""
    axes = persona["axes"]
    place = "출퇴근하는 사람이 많은" if axes["motive"] == "habitual" else "머무는 사람이 섞인"
    return (
        f"{features['area_nm']} 상권({place} 동네)의 {persona['demo']}. "
        f"주로 {TIME_KO[axes['time']]} 시간대에 움직이고, 이 동네 {features['category_nm']} "
        f"객단가는 {features['avg_ticket']:,}원이다."
    )


def build_panel(
    features: dict[str, Any],
    narrator: Callable[[list[dict[str, Any]], dict[str, Any]], list[str]] | None = None,
) -> list[dict[str, Any]]:
    """상권 피처 → 페르소나 12개.

    narrator 를 주면 서사 생성을 위임한다(LLM 배치 1콜). 없으면 사실 나열로 채운다.
    """
    gender, age = features["gender_share"], features["age_share"]
    bound = boundary_age(features)

    base_axes = {"price_sens": price_sens(features), "motive": motive(features)}
    seeds = [
        {"gender": g, "age": a, "weight": round(gender[g] * age[a], 4)}
        for a in sorted(age)
        for g in ("M", "F")
    ]
    times = _assign_times([s["weight"] for s in seeds], features["time_share"])

    personas: list[dict[str, Any]] = []
    for i, (seed, time) in enumerate(zip(seeds, times, strict=True), start=1):
        g, a = seed["gender"], seed["age"]
        demo = f"{AGE_LABEL[a]} {'남성' if g == 'M' else '여성'}"
        is_boundary = a == bound
        evidence = [
            {"path": f"gender_share.{g}", "value": gender[g]},
            {"path": f"age_share.{a}", "value": age[a]},
        ]
        # 경계 페르소나는 '유동 대비 매출이 낮다'는 것 자체가 근거다.
        evidence.append(
            {"path": f"foot_age_share.{a}", "value": features["foot_age_share"][a]}
            if is_boundary
            else {
                "path": f"time_share.{_band_of(time, features)}",
                "value": features["time_share"][_band_of(time, features)],
            }
        )
        personas.append(
            {
                "persona_id": f"p{i:02d}",
                "demo": demo,
                "axes": {**base_axes, "time": time},
                "weight": seed["weight"],
                "is_boundary": is_boundary,
                "narrative": "",
                "evidence": evidence,
            }
        )

    texts = (
        narrator(personas, features)
        if narrator
        else [stub_narrative(p, features) for p in personas]
    )
    for p, text in zip(personas, texts, strict=True):
        p["narrative"] = text
    return personas


def _band_of(time_label: str, features: dict[str, Any]) -> str:
    """시간 축 라벨 → 그 라벨을 만든 매출 시간대 키. 같은 라벨이 둘이면 큰 쪽."""
    cands = [
        b for b, lab in TIME_LABEL.items() if lab == time_label and b in features["time_share"]
    ]
    return max(cands, key=lambda b: features["time_share"][b])
