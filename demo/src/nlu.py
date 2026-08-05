"""자연어 입력에서 슬롯을 뽑아낸다 — 현재는 키워드 매칭 스텁.

━━ 실제 모델로 교체할 지점 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
extract() 내부만 갈아끼우면 된다. 호출부는 바뀌지 않는다.

  LLM 에 structured output(또는 function calling)으로 아래 스키마를 요구한다.
      goal      copy | image
      industry  industries.yaml 의 id 중 하나
      format    formats.yaml 의 id 중 하나
      style     styles.yaml 의 id 중 하나
      product   상품명 (자유 문자열)

  ⚠️ 못 알아들은 슬롯은 **비워서 반환해야 한다.** 억지로 채우면
     사장님이 말하지 않은 조건이 광고에 반영된다.
     비어 있으면 대화가 그 항목만 되묻는다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

반환값에는 **근거가 된 표현**을 함께 담는다.
"'인스타'라고 하셔서 인스타 피드로 잡았어요" 처럼 사용자에게 보여주기 위함이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import registry


@dataclass
class Slot:
    value: str
    evidence: str  # 이 값을 뽑아낸 근거 표현


# 키워드 사전 — LLM 으로 교체되면 이 사전은 폴백으로만 남는다.
GOAL_HINTS: dict[str, list[str]] = {
    "copy": ["문구", "글", "카피", "문장", "멘트", "글귀"],
    "image": ["사진", "이미지", "그림", "포스터", "배너", "전단", "메뉴판", "썸네일", "디자인"],
}

INDUSTRY_HINTS: dict[str, list[str]] = {
    "cafe": ["카페", "커피", "디저트", "베이커리", "케이크", "음료", "빵집"],
    "restaurant": ["음식점", "식당", "분식", "백반", "국밥", "고깃집", "치킨", "밥집"],
    "butcher": ["정육", "반찬", "청과", "과일", "정육점", "마트", "슈퍼"],
    "salon": ["미용실", "네일", "속눈썹", "헤어", "펌", "염색", "미용"],
    "flower": ["꽃집", "꽃", "공방", "소품", "화분", "꽃다발"],
    "academy": ["학원", "공부방", "교습소", "과외", "수업", "특강", "개강"],
    "fitness": ["헬스", "필라테스", "요가", "피트니스", "PT", "짐"],
}

# ⚠️ 구체적인 것을 먼저 둔다. "인스타 스토리"는 스토리로 잡혀야 하는데,
#    insta_feed 의 "인스타"가 먼저 걸리면 피드로 오인된다.
FORMAT_HINTS: dict[str, list[str]] = {
    "insta_story": ["스토리", "릴스"],
    "delivery_thumb": ["배달", "배민", "요기요", "쿠팡이츠", "썸네일"],
    "menu_board": ["메뉴판", "가격표", "팝", "POP"],
    "flyer_a4": ["전단", "전단지", "인쇄", "찌라시"],
    "banner_wide": ["배너", "가로형"],
    "insta_feed": ["인스타그램", "인스타", "피드"],   # 가장 포괄적 → 마지막
}

STYLE_HINTS: dict[str, list[str]] = {
    "warm": ["따뜻", "감성", "포근", "아늑", "정겨운"],
    "modern": ["모던", "심플", "깔끔", "미니멀", "세련"],
    "bold": ["특가", "할인", "세일", "강렬", "눈에 띄", "이벤트", "파격"],
    "natural": ["신선", "내추럴", "자연", "건강", "싱싱"],
}

# 상품명 추출 시 걸러낼 표현
_STOPWORDS = {
    "우리", "저희", "가게", "매장", "신메뉴", "메뉴", "새로", "이번", "이번주", "오늘",
    "좀", "하나", "것", "거", "광고", "홍보", "만들어줘", "만들어", "만들고", "올릴",
    "올리려고", "해줘", "주세요", "부탁", "싶어", "싶은데", "필요해", "필요한데",
    # 키워드를 걷어낸 뒤 남는 조사·어미 조각. 안 지우면 상품명에 섞인다.
    # 예) "카페인데" 에서 '카페'를 지우면 '인데'가 남아 "인데 크로플"이 된다.
    "인데", "인데요", "이고", "이라", "라서", "에서", "한테", "까지", "부터",
    "이랑", "같은", "그냥", "관련", "사장", "사장님", "대표",
}
_JOSA = re.compile(r"(을|를|이|가|은|는|에|의|로|으로|랑|이랑|하고|도)$")


def _match(text: str, hints: dict[str, list[str]]) -> Slot | None:
    """가장 긴 키워드가 먼저 걸리도록 정렬해서 매칭한다."""
    best: tuple[str, str] | None = None
    for key, words in hints.items():
        for w in words:
            if w in text and (best is None or len(w) > len(best[1])):
                best = (key, w)
    return Slot(best[0], best[1]) if best else None


def _all_keywords(text: str) -> list[str]:
    """문장에 등장하는 모든 사전 키워드. 상품명 추출 시 전부 걷어낸다.

    이기지 못한 후보도 지워야 한다. 예) "인스타 스토리"에서 규격은 스토리로 잡히지만
    "인스타"가 남아 상품명으로 오인되면 안 된다.
    """
    hit = []
    for hints in (GOAL_HINTS, INDUSTRY_HINTS, FORMAT_HINTS, STYLE_HINTS):
        for words in hints.values():
            hit += [w for w in words if w in text]
    return sorted(hit, key=len, reverse=True)


def _is_candidate(token: str) -> bool:
    if len(token) < 2 or token in _STOPWORDS:
        return False
    return not any(v in token for v in ("만들", "올리", "해주", "하고싶", "필요", "부탁"))


def _extract_product(text: str) -> Slot | None:
    """상품명 추정 — 사전 키워드와 불용어를 걷어내고 남는 연속 토큰 (최대 2개).

    ⚠️ 휴리스틱이다. LLM 으로 교체하면 이 함수는 통째로 사라진다.
    """
    cleaned = text
    for w in _all_keywords(text):
        cleaned = cleaned.replace(w, " ")

    run: list[str] = []
    for raw in cleaned.split():
        token = _JOSA.sub("", raw.strip(" ,.!?~\"'"))
        if _is_candidate(token):
            run.append(token)
            if len(run) == 2:
                break
        elif run:
            break
    return Slot(" ".join(run), " ".join(run)) if run else None


def extract(text: str) -> dict[str, Slot]:
    """자연어 → 슬롯. **못 알아들은 것은 넣지 않는다.**"""
    text = (text or "").strip()
    if not text:
        return {}

    found: dict[str, Slot] = {}
    for slot_name, hints in (
        ("goal", GOAL_HINTS),
        ("industry", INDUSTRY_HINTS),
        ("format", FORMAT_HINTS),
        ("style", STYLE_HINTS),
    ):
        hit = _match(text, hints)
        if hit:
            found[slot_name] = hit

    # ⚠️ 상품명은 **다른 슬롯이 하나라도 잡혔을 때만** 뽑는다.
    #    휴리스틱이 아무 문자열이나 통과시키기 때문이다.
    #    "카페 크로플" → 크로플 ✅ / "ㅁㄴㅇㄹ" → 아무것도 안 잡힘 ✅
    #    상품명만 단독으로 말한 경우("크로플")는 상품명을 묻는 질문에서
    #    입력 자체를 답으로 받으므로 손실이 없다.
    if found:
        product = _extract_product(text)
        if product:
            found["product"] = product

    # 규격을 말했는데 목적을 안 말한 경우 → 이미지로 본다
    if "format" in found and "goal" not in found:
        found["goal"] = Slot("image", found["format"].evidence)

    return found


LABELS = {
    "goal": "무엇을 만들지",
    "industry": "업종",
    "format": "규격",
    "style": "느낌",
    "product": "홍보 대상",
}


def describe(slot_name: str, value: str) -> str:
    """슬롯 값을 사람이 읽을 수 있는 문구로."""
    if slot_name == "goal":
        return "광고 문구" if value == "copy" else "광고 이미지"
    if slot_name == "product":
        return value
    source = {"industry": registry.industries, "format": registry.formats, "style": registry.styles}
    try:
        item = registry.by_id(source[slot_name](), value)
        return f"{item.get('emoji', '')} {item['label']}".strip()
    except (KeyError, TypeError):
        return value
