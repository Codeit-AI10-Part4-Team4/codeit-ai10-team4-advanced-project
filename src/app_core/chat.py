"""챗봇 — 사장님 말에서 주문서를 채운다.

매 턴 LLM 이 **메시지와 선택지를 함께** 낸다. 선택지는 힌트일 뿐이고,
사장님은 자연어로 답해도 되고 클릭해도 된다.

선택지를 미리 정해두지 않고 LLM 이 만드는 이유는, 상황마다 물어볼 게 달라서
경우의 수를 열거할 수 없고 목록에 없는 상황이 오면 대응이 안 되기 때문이다.

LLM 이 지어낸 값이 그대로 주문서에 들어가지 않도록, 뽑아낸 값은 슬롯 하나씩
AdBriefDraft 로 다시 검증한다.
"""

from __future__ import annotations

from pydantic import ValidationError

from app_core.llm import ChatClient, get_client
from app_core.schema import AdBriefDraft, ChatTurn, Store

SYSTEM_PROMPT = """너는 동네 가게 사장님이 광고를 만들도록 돕는 챗봇이다.

가게: {industry} · {store_name}
사장님이 만들려는 것: {goal}

# 이미 알고 있는 것
{filled}

# 아직 모르는 필수 항목
{missing}

# 할 일
1. 사장님의 **이번 말**에서 새로 알아낸 것을 extracted 에 넣는다.
2. {next_action}

# extracted 규칙 — 가장 중요하다
- **이번 말에서 새로 알아낸 것만** 넣어라. 이미 알고 있는 것을 되풀이해 넣지 마라.
- 느낌·분위기를 말하면 tone 에 넣어라. 놓치기 쉬우니 특히 주의해라.
    "매운 감칠맛을 부각해줘"  →  tone: "매운 감칠맛 강조"
    "중독성 있게"             →  tone: "중독성 있는"
    "따뜻한 느낌으로"         →  tone: "따뜻한"
- 무엇을 알리는 광고인지 말하면 situation 에 넣어라.
    "신메뉴 나왔어요"  →  situation: "신메뉴"
    "이번 주만 할인"   →  situation: "할인·특가"
- 가격은 **사장님이 말했을 때만** 넣어라. 숫자만 넣는다.
    "26000원"                  →  price: 26000
    "가격은 안 넣을래요"        →  price: 0
    가격 얘기가 없었다  →  price 를 **아예 넣지 마라.** 0 도 넣지 마라.
    (0 은 "가격을 빼달라"는 뜻이다. 모르겠다는 뜻이 아니다)
- 이번 말에서 아무것도 못 알아냈으면 extracted 를 비워라.
- **없는 사실을 지어내지 마라.** 사장님이 말하지 않은 가격·메뉴를 넣지 마라.

# 말투
사장님은 광고 전문가가 아니다. 쉬운 말로 짧게 말해라.

아래 JSON 형식으로만 답해라.

{{
  "message": "사장님에게 할 말",
  "options": ["선택지1", "선택지2"],
  "extracted": {{"product": "...", "price": 숫자, "situation": "...", "tone": "...", "extra": "..."}}
}}

extracted 안의 항목은 이번 말에서 알아낸 것만 남기고 나머지는 지워라.

# 예시
사장님: "우리 가게 신메뉴 나왔는데 문구 좀 만들어줘"
{{
  "message": "어떤 메뉴인가요?",
  "options": ["직접 입력할게요"],
  "extracted": {{"situation": "신메뉴"}}
}}
→ 메뉴 이름과 가격은 아직 모르니 넣지 않았고, "신메뉴"는 **알아냈으므로 넣었다.**
   필수가 아니어도 알아낸 것은 빠짐없이 넣어라.
"""

# 필수가 다 찼는지에 따라 다음에 할 일이 달라진다. 이걸 안 갈라주면
# LLM 이 선택 항목을 채우려고 같은 질문을 계속 되풀이한다.
ASK_MORE = """필수 항목 중 **하나만** 물어라. 한 번에 여러 개 묻지 마라.
   말로 설명하기 어려울 때 누를 수 있도록 선택지(options)를 2~4개 함께 줘라."""

WRAP_UP = """필수가 다 찼다. **더 묻지 말고 마무리해라.**
   "이제 만들어드릴게요" 처럼 알리고 options 는 반드시 빈 배열로 둬라.
   느낌·상황 같은 나머지는 사장님이 말한 것만 채우면 된다."""

GOAL_LABEL = {"image": "광고 이미지", "copy": "광고 문구"}

# LLM 이 뽑아낼 수 있는 슬롯. goal 은 고정 버튼으로 정해지므로 여기 없다.
_SLOTS = ("product", "price", "situation", "tone", "extra")

SLOT_LABEL = {
    "product": "홍보할 상품·메뉴",
    "price": "가격",
    "situation": "알리려는 것",
    "tone": "원하는 느낌",
    "extra": "그 밖의 요청",
}


def _describe(draft: AdBriefDraft) -> str:
    filled = [
        f"- {SLOT_LABEL[s]}: {getattr(draft, s)}"
        for s in _SLOTS
        if getattr(draft, s) not in (None, "")
    ]
    return "\n".join(filled) if filled else "(아직 없음)"


def _system_prompt(draft: AdBriefDraft, store: Store) -> str:
    missing = draft.missing()
    return SYSTEM_PROMPT.format(
        industry=store.industry_label,
        store_name=store.name,
        goal=GOAL_LABEL.get(draft.goal or "", "미정"),
        filled=_describe(draft),
        missing=", ".join(SLOT_LABEL[s] for s in missing) if missing else "(없음 — 다 찼다)",
        next_action=ASK_MORE if missing else WRAP_UP,
    )


def _safe_extract(raw: dict) -> AdBriefDraft:
    """슬롯 하나씩 검증한다. 틀린 슬롯만 버리고 나머지는 살린다."""
    safe: dict = {}
    for slot in _SLOTS:
        if slot not in raw:
            continue
        try:
            AdBriefDraft(**{**safe, slot: raw[slot]})
        except ValidationError:
            continue
        safe[slot] = raw[slot]
    return AdBriefDraft(**safe)


def respond(
    draft: AdBriefDraft,
    utterance: str,
    store: Store,
    client: ChatClient | None = None,
) -> ChatTurn:
    """한 턴 처리 — 사장님 말을 듣고 주문서를 갱신한 뒤 다음 질문을 낸다."""
    raw = (client or get_client()).complete_json(_system_prompt(draft, store), utterance)

    merged = draft.merge(_safe_extract(raw.get("extracted") or {}))
    options = raw.get("options")
    return ChatTurn(
        message=str(raw.get("message") or "조금 더 자세히 말씀해주시겠어요?"),
        # 필수가 다 찼으면 선택지를 지운다 — LLM 이 지시를 어기고 또 물어봐도
        # 화면에는 안 뜨게 해서 대화가 맴돌지 않게 한다.
        options=[str(o) for o in options] if isinstance(options, list) and merged.missing() else [],
        draft=merged,
    )
