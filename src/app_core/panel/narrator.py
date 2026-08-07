"""페르소나 서사 생성 — 패널 전체를 배치 1콜로 처리한다.

**LLM 이 손대는 곳은 여기 한 곳뿐이다.** 비중·축·근거는 전부 코드가 정하고
(`panel_builder`), 여기서는 그 값을 사람이 읽을 문장으로 옮기기만 한다.
서사는 근거가 아니라 코멘트 가독성을 위한 것이다 (07 §4.6 — C 등급).

12명을 12콜로 부르지 않는 이유: 같은 상권을 12번 설명하게 되고, 서로 겹치는
서사가 나온다. 한 번에 넘기면 모델이 12명을 **서로 다르게** 쓸 수 있다.
"""

from __future__ import annotations

from typing import Any

from app_core.llm import get_client

TIME_KO = {
    "morning": "아침(6~11시)",
    "weekday_lunch": "점심(11~14시)",
    "afternoon": "오후(14~17시)",
    "evening": "저녁(17~21시)",
    "night": "늦은 시간",
}
PRICE_KO = {"low": "가격 저항이 낮은", "mid": "보통", "high": "가격에 민감한"}
MOTIVE_KO = {"habitual": "늘 가던 곳을 다시 찾는", "exploratory": "새로운 곳을 찾아보는"}

SYSTEM = """상권 데이터를 손님 소개글로 옮긴다. 이 글은 나중에 그 손님이 광고를
평가할 때 "당신은 이런 사람입니다"로 들어간다.

각 손님을 **2문장**으로 쓴다.
  1문장 — 이 동네에서 언제·어떻게 움직이는 사람인지 (주어진 시간대·동네 성격만)
  2문장 — 가게를 고를 때 무엇을 보는지 (주어진 가격 성향·방문 성향만)

**지어내면 안 되는 것** — 아래는 데이터에 없다. 한 글자도 쓰지 마라.
  직업·회사·소득 ("회사원", "팀장", "학생")
  동행자 ("동료와", "가족과", "친구와")
  취향·브랜드 ("커피를 좋아해서", "인스타를 보고")
  주어지지 않은 수치

**나쁜 예** (전부 지어낸 것)
  "역삼역 근처 회사에 다니는 30대 남성. 동료들과 점심 후 커피를 마신다."
**좋은 예** (주어진 것만)
  "평일 점심 무렵에 이 동네를 오가는 30대 남성이다. 늘 가던 곳을 다시 찾는 편이라
   새로 생긴 가게에는 잘 눈이 가지 않는다."

**분석 용어를 문장에 쓰지 마라.** 이건 손님을 설명하는 글이지 통계 설명이 아니다.
  금지: "매출 비중", "데이터", "평균", "비중", "층", "%", "배"
  나쁜 예: "매출 비중보다 더 많이 소비한다"
  좋은 예: "이 동네에서 이런 가게를 자주 이용하는 편이다"

**핵심 고객 / 놓치는 층은 행동으로 표현한다.**
  많이 사는 층 → "이런 가게를 자주 이용하는 편이다"
  평범한 층   → 이 얘기를 굳이 넣지 말고 시간대·성향만 쓴다
  적게 사는 층 → "이 근처를 지나다니지만 이런 가게에는 잘 들르지 않는다"
                 (경계 손님은 이 문장이 **반드시** 들어가야 한다)

12명이 서로 다른 문장이어야 한다. 사장님이 읽을 글이라 전문용어는 쓰지 않는다.
응답은 JSON 하나로만: {"p01": "문장", "p02": "문장", ...}"""


def _pool_ratio(p: dict[str, Any], features: dict[str, Any]) -> str:
    """이 연령대가 '있는 만큼 사는가'. 페르소나마다 다른 유일한 실측값이다.

    축(price_sens·motive)은 상권 단위라 전원 같다. 이 비율을 주지 않으면
    모델이 12명을 구별할 재료가 나이·성별뿐이라 서사가 전부 같아진다.
    """
    age = p["demo"][:2]
    pool = max(
        (features.get("foot_age_share") or {}).get(age, 0.0),
        (features.get("back_age_share") or {}).get(age, 0.0),
    )
    share = features["age_share"].get(age, 0.0)
    if pool <= 0 or share <= 0:
        return ""
    r = share / pool
    if r >= 1.15:
        return f" 이 동네에 있는 비중보다 **실제로 사는 비중이 {r:.1f}배 높다**(핵심 고객)."
    if r <= 0.85:
        return f" 이 동네에 있는 비중의 **{r:.1f}배만큼만 산다**(놓치고 있는 층)."
    return " 있는 만큼 사는, 평범한 비중의 층이다."


def _persona_line(p: dict[str, Any], features: dict[str, Any]) -> str:
    axes = p["axes"]
    return (
        f"- {p['persona_id']}: {p['demo']}, 이 업종 매출의 {p['weight'] * 100:.1f}%. "
        f"{TIME_KO.get(axes['time'], axes['time'])}에 주로 움직임. "
        f"{MOTIVE_KO[axes['motive']]} 편, {PRICE_KO[axes['price_sens']]} 동네."
        + _pool_ratio(p, features)
    )


def build_prompt(personas: list[dict[str, Any]], features: dict[str, Any]) -> str:
    place = (
        "출퇴근하는 사람이 많은 동네"
        if (features.get("work_ratio") or 0) >= 0.7
        else "사는 사람과 오가는 사람이 섞인 동네"
    )
    return (
        f"## 동네\n{features['area_nm']} ({features['gu_nm']} {features['dong_nm']}), "
        f"{features['area_type']}, {place}\n"
        f"이 동네 {features['category_nm']} 객단가 {features['avg_ticket']:,}원, "
        f"경쟁 점포 {features['competitor_cnt']}곳, 주말 매출 비중 "
        f"{features['weekend_ratio'] * 100:.0f}%\n\n"
        "## 손님 12명\n" + "\n".join(_persona_line(p, features) for p in personas)
    )


def narrate(personas: list[dict[str, Any]], features: dict[str, Any]) -> list[str]:
    """`build_panel(features, narrator=narrate)` 로 넘겨 쓴다.

    모델이 답을 못 주면(스텁 프로필·응답 누락) 빈 문자열 대신 사실 나열로 남긴다 —
    서사가 비어도 평가는 돌아야 한다.
    """
    from app_core.panel.panel_builder import stub_narrative

    reply = get_client().complete_json(SYSTEM, build_prompt(personas, features))
    return [
        str(reply.get(p["persona_id"]) or stub_narrative(p, features)).strip() for p in personas
    ]
