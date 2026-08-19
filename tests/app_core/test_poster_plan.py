"""기획 부품 테스트 — LLM 을 대역으로 바꿔 실제 호출 없이 검증한다 (팀 규칙).

대역을 `ChatClient` 로 세운다. 전에는 `openai.OpenAI` 를 통째로 갈아끼웠는데,
그건 우리 계약이 아니라 남의 라이브러리 모양을 흉내 내는 것이라 SDK 가 바뀌면
같이 깨진다. 게다가 openai 가 없는 CI 에서는 파일째 건너뛰어 검사되지 않았다.
"""

import pytest

from app_core import poster_plan


class FakePlanner:
    """`plan_poster` 가 부르는 것은 `complete_json` 하나뿐이다."""

    def __init__(self, payload: dict):
        self.payload = payload

    def complete_json(self, system: str, user: str) -> dict:
        return self.payload


def test_plan_poster_parses_fields():
    plan = poster_plan.plan_poster(
        "연남 플라워",
        "꽃집",
        "봄 꽃다발",
        client=FakePlanner(
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
    assert plan.badge == "봄 시즌"
    assert len(plan.features) == 3
    assert plan.palette in poster_plan.PALETTES


def test_plan_poster_allows_empty_event():
    """말하지 않은 이벤트·날짜는 비어 있어야 한다 — 지어내면 허위광고가 된다."""
    plan = poster_plan.plan_poster(
        "연남 플라워",
        "꽃집",
        "꽃다발",
        client=FakePlanner(
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
    assert plan.date_line == ""
    assert plan.event == ""


def test_unknown_palette_is_rejected():
    """모르는 팔레트 이름이 오면 그리기 전에 걸러야 한다."""
    bad = FakePlanner(
        {
            "tagline": "x",
            "badge": "y",
            "date_line": "",
            "features": ["a|b"],
            "event": "",
            "palette": "노랑무지개",
        }
    )
    with pytest.raises(ValueError):
        poster_plan.plan_poster("가게", "꽃집", "꽃", client=bad)


def test_빈_응답은_원인을_말한다():
    """MODEL_PROFILE 이 stub 이면 여기로 온다.

    그냥 넘기면 pydantic 이 "필드 5개 없음"으로 터져서 화면에서는 무엇이
    잘못됐는지 알 수가 없다.
    """
    with pytest.raises(ValueError, match="MODEL_PROFILE"):
        poster_plan.plan_poster("가게", "꽃집", "꽃", client=FakePlanner({}))


# ── 지어내기 방지 (프롬프트 계약) ──────────────────────────────


def test_기본값은_전부_빈칸이다():
    """근거가 없으면 비우는 게 정답 — palette 만 필수다."""
    plan = poster_plan.PosterPlan(palette="fresh_mint")
    assert plan.tagline == "" and plan.badge == "" and plan.date_line == ""
    assert plan.features == [] and plan.event == ""


def test_정보가_없는_주문은_빈_블록으로_받는다():
    """평범한 카페 주문 — 모델이 tagline·palette 만 채워 보내도 정상 파싱된다."""
    plan = poster_plan.plan_poster(
        "동네 카페",
        "카페·디저트",
        "아메리카노",
        client=FakePlanner({"tagline": "천천히 머무는 오후", "palette": "warm_bakery"}),
    )
    assert plan.features == [] and plan.badge == "" and plan.event == ""


def test_사장님이_말한_정보는_유지된다():
    plan = poster_plan.plan_poster(
        "연남 플라워",
        "꽃집",
        "봄 꽃다발",
        transcript="3월 한 달 할인해요. 선물하기 좋게 정성껏 포장해드려요",
        client=FakePlanner(
            {
                "tagline": "봄과 함께",
                "badge": "봄 시즌",
                "date_line": "3월",
                "features": ["선물 포장|정성껏 포장"],
                "event": "3월 한 달 할인",
                "palette": "soft_pink",
            }
        ),
    )
    assert plan.event == "3월 한 달 할인"
    assert plan.date_line == "3월"
    assert plan.features == ["선물 포장|정성껏 포장"]


def test_프롬프트에_지어내기_금지_계약이_있다():
    """막는 것은 코드가 아니라 프롬프트다 — 계약 문구가 사라지면 이 테스트가 잡는다."""
    s = poster_plan._SYSTEM
    assert "말하지 않은 것은 쓰지 않는다" in s
    assert "추론하지 마라" in s
    assert "사실과 다른 광고" in s


def test_프롬프트는_팔레트를_반드시_고르게_한다():
    """실측(2026-08-19 스모크): "근거 없으면 빈칸" 규칙을 모델이 palette 에도
    적용해 빈 문자열을 보냈고, 검증기가 포스터 생성 전체를 막았다.
    이 문구가 프롬프트에서 빠지면 같은 사고가 재발한다."""
    assert "palette 는 빈칸 금지" in poster_plan._SYSTEM
    assert "반드시 하나 고른다" in poster_plan._SYSTEM
