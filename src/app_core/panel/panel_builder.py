"""상권 피처 → 가상 손님 패널.

`build_features()` 결과를 받아 페르소나 12개(성별 2 × 연령 6)를 만든다.
**축 값·가중치는 전부 코드가 정하고, LLM 은 서사 한 문장만 쓴다** (07 §7.1).

축을 어떤 근거로 정하는지가 이 파일의 전부다. 근거 없는 다양성은 만들지 않는다.

  price_sens  상권 객단가 분위 + 아파트 시가 + **나이대별 객단가** → 페르소나마다 다름
  motive      work_ratio (출퇴근 상권인가)          → 상권 단위 (전원 동일)
  time        매출 시간대 분포에 맞춰 배분          → 페르소나마다 다름
  weight      gender_share × age_share             → 두 축의 곱

**근거 없는 다양성은 만들지 않는다**가 이 파일의 원칙이고, 그건 안 바뀌었다.
바뀐 것은 근거다 — 서울시 원본에 `연령대_N_매출_금액` 과 **`건수`가 둘 다** 있어서
나이대별 객단가를 실측으로 구할 수 있다. 우리 ETL 이 건수를 안 싣고 있었을 뿐이다.

    역삼역 커피-음료     10대  6,420원  →  60대+ 10,023원   (나이 들수록 오름)
    홍대입구역 커피-음료  10대 12,626원  →  60대+  7,833원   (나이 들수록 내림)

같은 업종인데 상권마다 방향이 반대다. 계수로는 절대 못 만드는 값이라 근거 등급 A 다.

price_sens 를 상권 단위로 두던 동안 손님 12명은 같은 숫자와 견주었고, 그래서
가격 판단이 하나로 모였다 (실측 2026-08-12: 12명 중 10명이 걸림돌로 price 를 골랐고
그중 5명은 코멘트가 글자 하나 안 틀리고 같았다). motive 는 아직 상권 단위인데,
`work_ratio` 를 나이대로 쪼갤 실측 근거가 없어서 그대로 둔다.
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


#: 저항이 높은 쪽 → 낮은 쪽. `_shift` 가 이 순서로 한 칸씩 옮긴다.
SENS_LEVELS: Final = ("high", "mid", "low")

#: 그 나이대 객단가가 동네 기준의 이 배율 밖이면 한 칸 옮긴다.
#:
#: 서울 전체를 쓸어서 정했다 — (상권×업종) 14,231개 조합, 비율 표본 64,061개.
#:
#:     비율 분포   p5 0.55   p25 0.86   중앙 0.99   p75 1.09   p95 1.43
#:
#:     문턱          12명이 갈리는 조합   한 칸 이상 움직인 나이대
#:     0.80~1.20          66.4%                31.3%
#:     0.85~1.15          77.9%                41.3%   ← 여기
#:     0.90~1.10          88.8%                55.3%
#:     0.95~1.05          96.6%                75.1%
#:
#: 대략 사분위 바깥이라, 또래와 견줘 **꼬리에 있는 나이대만** 움직인다.
#: 더 좁히면 절반 넘는 손님이 한 칸씩 밀려 "다양성"이 아니라 잡음이 되고,
#: 더 넓히면 3분의 1이 지금처럼 한 덩어리로 남는다.
AGE_TICKET_LOW: Final = 0.85
AGE_TICKET_HIGH: Final = 1.15


def _shift(level: str, step: int) -> str:
    i = SENS_LEVELS.index(level) + step
    return SENS_LEVELS[max(0, min(len(SENS_LEVELS) - 1, i))]


def _age_ticket_ratio(features: dict[str, Any], age: str | None) -> float | None:
    """그 나이대 객단가 ÷ 동네 기준. 잴 수 없으면 None.

    기준은 `avg_ticket` 이 아니라 `age_ticket_base` 다. `avg_ticket` 에는 나이 미상
    매출이 섞여 있어(역삼 커피는 알려진 나이가 82%뿐) 나이대끼리 견주는 자로는
    못 쓴다 — 그걸 쓰면 여섯 칸 중 다섯이 전부 아래로 몰린다.
    """
    if age is None:
        return None
    ticket = (features.get("age_ticket") or {}).get(age)
    base = features.get("age_ticket_base") or 0
    if not ticket or not base:
        return None
    return ticket / base


def price_sens(features: dict[str, Any], age: str | None = None) -> str:
    """가격 저항. 상권 객단가 분위가 기준이고, 배후 아파트 시가와 **나이대**로 보정한다.

    객단가가 높다 = 그 동네 손님이 그 값을 내고 있다 = 가격 저항이 낮다.

    `age` 를 주면 **그 나이대가 이 동네에서 실제로 한 번에 쓰는 돈**으로 한 칸 옮긴다.
    상권 값 하나만 쓰면 12명이 같은 숫자와 견주게 되어 가격 판단이 하나로 모인다
    (실측 2026-08-12: 손님 12명 중 10명이 걸림돌로 price 를 골랐고, 그중 5명은
    코멘트가 글자 하나 안 틀리고 같았다).

    지어낸 계수가 아니라 서울시 원본의 `연령대_N_매출_금액 ÷ 건수` 다. 그래서 이
    파일 맨 위의 "근거 없는 다양성은 만들지 않는다"를 어기지 않는다 — 근거가 생겼다.
    건수가 적어 믿을 수 없는 칸은 `age_ticket` 이 `None` 이고, 그러면 상권 값을 쓴다.
    """
    pct = features.get("avg_ticket_pct", 0.5)
    level = "low" if pct > 0.75 else "high" if pct < 0.25 else "mid"
    apt = features.get("apt_avg_price")
    if apt and apt > APT_PRICE_HIGH and level != "low":
        # 비싼 아파트가 배후면 소득이 받쳐준다 — 한 단계 완화
        level = "mid" if level == "high" else "low"

    ratio = _age_ticket_ratio(features, age)
    if ratio is not None:
        # 또래보다 적게 쓰는 나이대 = 이 가격이 더 부담스럽다
        if ratio < AGE_TICKET_LOW:
            level = _shift(level, -1)
        elif ratio > AGE_TICKET_HIGH:
            level = _shift(level, +1)
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
    """상권 피처 → 페르소나 **최대** 12명. 매출이 0 인 연령대는 빠진다.

    narrator 를 주면 서사 생성을 위임한다(LLM 배치 1콜). 없으면 사실 나열로 채운다.
    """
    gender, age = features["gender_share"], features["age_share"]
    bound = boundary_age(features)

    # motive 만 상권 단위다. price_sens 는 나이대별 실측 객단가가 있어 사람마다 갈린다.
    base_motive = motive(features)
    seeds = [
        {"gender": g, "age": a, "weight": round(gender[g] * age[a], 4)}
        for a in sorted(age)
        for g in ("M", "F")
    ]
    # **매출이 0 인 연령대는 손님이 아니다 — 페르소나를 만들지 않는다.**
    #
    # 안 거르면 `Persona.weight` 의 `gt=0.0` 에 걸려 ValidationError 가 난다.
    # 화면에서는 `_rank_copies` 가 잡는 예외 축(NoTradeAreaError·AggregationError)
    # 밖이라 빨간 트레이스백이 사장님에게 그대로 뜬다.
    #
    # 여태 안 보인 이유는 관통 실행을 **좌표 박아둔 역삼·홍대·수유에서만** 했기
    # 때문이다. 랜덤 상권으로 돌려보고서야 나왔다 (실측 2026-08-19, 9곳 중 4곳 사망):
    #
    #     난우중학교 미용실   20대 매출 0원
    #     동평화시장 한식     10대 매출 0원
    #     주소 × 업종 50,016 조합 중 10,448 (20.9%) · 상권 1,428 / 1,649 이 해당
    #
    # 하한 가중치를 주는 쪽도 됐지만 **없는 비중을 지어내는 것**이라 안 했다.
    # 점수는 어느 쪽이든 같다 — 가중치 0 은 가중평균에 기여하지 않는다.
    # 빠지는 층이 '지나다니지만 안 사는' 정보를 갖는 경우는 `boundary_age` 가
    # 맡는데, 거기는 이미 `BOUNDARY_MIN_SHARE` 미만을 제외한다. 즉 **여기서
    # 빠지는 층이 경계 페르소나가 될 일은 없다** — 잃는 정보가 없다.
    seeds = [s for s in seeds if s["weight"] > 0]
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
                "axes": {
                    "price_sens": price_sens(features, a),
                    "motive": base_motive,
                    "time": time,
                },
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


class WeightError(ValueError):
    """사장님이 넘긴 비중이 말이 안 된다. 화면에 그대로 보여줄 문장이다."""


def adjust_weights(
    personas: list[dict[str, Any]], overrides: dict[str, float]
) -> list[dict[str, Any]]:
    """사장님이 고친 비중을 반영한다 (R1 — 슬라이더 조정).

    데이터가 정한 비중이 내 가게와 다를 수 있다. "우리는 주말 20대가 훨씬 많아요"
    같은 경우다. 고친 값은 **그대로 쓰고, 나머지 손님들이 남은 몫을 원래 비율대로
    나눠 갖는다.** 손대지 않은 손님들 사이의 상대 관계는 유지된다.

    저장하지 않는다 — 화면이 값을 들고 있다가 평가할 때 같이 넘긴다. 패널은
    (가게, 업종)에서 결정적으로 다시 만들 수 있으므로 통째로 보관할 이유가 없다.
    """
    if not overrides:
        return personas

    known = {p["persona_id"] for p in personas}
    unknown = set(overrides) - known
    if unknown:
        raise WeightError(f"모르는 손님입니다: {sorted(unknown)}")
    if any(v < 0 for v in overrides.values()):
        raise WeightError("비중은 0보다 작을 수 없습니다.")

    fixed = sum(overrides.values())
    if fixed > 1.0:
        raise WeightError(f"고친 비중의 합이 100%를 넘습니다 ({fixed:.0%}).")

    rest = [p for p in personas if p["persona_id"] not in overrides]
    rest_total = sum(p["weight"] for p in rest)
    remaining = 1.0 - fixed

    out = []
    for p in personas:
        if p["persona_id"] in overrides:
            weight = overrides[p["persona_id"]]
        elif rest_total > 0:
            weight = p["weight"] / rest_total * remaining
        else:
            # 손대지 않은 손님이 전부 0이었다 — 남은 몫을 고르게 나눈다
            weight = remaining / len(rest) if rest else 0.0
        out.append({**p, "weight": round(weight, 4), "is_adjusted": p["persona_id"] in overrides})
    return out
