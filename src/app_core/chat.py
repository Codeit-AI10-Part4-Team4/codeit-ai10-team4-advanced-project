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
from app_core.schema import REQUIRED_SLOTS, AdBriefDraft, ChatTurn, Store

SYSTEM_PROMPT = """너는 동네 가게 사장님이 광고를 만들도록 돕는 챗봇이다.

가게: {industry} · {store_name}
사장님이 만들려는 것: {goal}

# 사장님이 지금까지 한 말
{transcript}

# 이미 알고 있는 것
{filled}

# 할 일 — 순서대로
1. 사장님의 **이번 말**에서 새로 알아낸 것을 extracted 에 넣는다.
   ⚠️ 이걸 먼저 해라. 물어볼 생각부터 하면 답이 눈앞에 있는데도 되묻게 된다.
2. {next_action}
   **단, 사장님이 이번 말에서 이미 알려줬다면 묻지 마라.** 짧게 확인하고 넘어가라.

# extracted 규칙 — 가장 중요하다
- **이번 말에서 새로 알아낸 것만** 넣어라. 이미 알고 있는 것을 되풀이해 넣지 마라.
- 한 문장에 여러 개가 들어 있으면 **빠짐없이 전부** 넣어라. 하나만 넣고 끝내지 마라.
- 홍보할 대상을 말하면 product 에 넣어라.
    "크로플 홍보하고싶어"  →  product: "크로플"
    "레드콤보요"           →  product: "레드콤보"
  **할인·행사 문장에도 상품이 들어 있다.** "반값"·"두 판 사면" 같은 말에
  정신이 팔려 상품명을 놓치지 마라.
    "이번 주만 아메리카노 반값이에요"  →  product: "아메리카노", situation: "할인"
    "피자 두 판 사면 콜라 줘요"        →  product: "피자", situation: "사은 행사"
- 느낌·분위기를 말하면 tone 에 넣어라. 놓치기 쉬우니 특히 주의해라.
    "매운 감칠맛을 부각해줘"  →  tone: "매운 감칠맛 강조"
    "중독성 있게"             →  tone: "중독성 있는"
    "따뜻한 느낌으로"         →  tone: "따뜻한"
- 왜 이 광고를 만드는지 말하면 situation 에 넣어라.
  **정해진 목록이 없다.** 사장님 말에 맞춰 자유롭게 써라. 틀에 안 맞는다고 비우지 마라.
    "신메뉴 나왔어요"              →  situation: "신메뉴 출시"
    "이번 주만 할인"               →  situation: "기간 한정 할인"
    "판매량이 저조해서요"          →  situation: "판매 부진 만회"
    "요즘 손님이 뜸해요"           →  situation: "손님 늘리기"
    "단골분들한테 감사 인사하려고"  →  situation: "단골 감사"
- 가격은 **세 경우를 구분**해라.
    ① 금액을 말했다        →  price: 그 숫자
        "26000원"  "2만 3천원"  "23,000원이에요"
    ② 가격을 **빼달라고** 했다  →  price: 0
        "가격은 빼주세요"  "가격 안 넣을래요"  "금액은 안 적을래요"
    ③ 가격 얘기가 **아예 없었다**  →  price 를 넣지 마라 (0 도 넣지 마라)
    ②와 ③을 헷갈리지 마라. ②는 사장님이 정한 것이고 ③은 아직 안 물어본 것이다.
    ②를 ③으로 처리하면 사장님이 이미 답한 것을 또 묻게 된다.
    **할인율은 금액이 아니다.** 아래는 전부 ③ 이다 — price 를 넣지 마라.
        "이번 주만 반값이에요"  "30프로 세일합니다"  "만원 할인"
        "아직 가격은 안 정했어요"
    할인한다는 말만으로는 얼마인지 알 수 없다. 0 을 넣으면 "가격을 빼달라"는
    뜻이 되어 사장님한테 가격을 영영 안 묻게 된다.
- 이번 말에서 아무것도 못 알아냈으면 extracted 를 비워라.
- **없는 사실을 지어내지 마라.** 사장님이 말하지 않은 가격·메뉴를 넣지 마라.

# 말투
사장님은 광고 전문가가 아니다. 쉬운 말로 짧게 말해라.

아래 JSON 형식으로만 답해라.

extracted 를 **먼저** 쓰고 그 다음에 message 를 써라. 순서를 지켜라.

{{
  "extracted": {{"product": "...", "price": 숫자, "situation": "...", "tone": "...", "extra": "..."}},
  "message": "사장님에게 할 말",
  "options": ["선택지1", "선택지2"]
}}

extracted 안의 항목은 이번 말에서 알아낸 것만 남기고 나머지는 지워라.

# extracted 예시
아래는 extracted 만 보여준다. message 와 options 는 매번 새로 써라 —
이 예시의 문장을 베끼지 마라.

    "크로플 홍보하고싶어"            →  {{"product": "크로플"}}
    "우리 가게 신메뉴 나왔는데"       →  {{"situation": "신메뉴 출시"}}
    "26000원이요"                    →  {{"price": 26000}}
    "따뜻하고 감성적으로"            →  {{"tone": "따뜻하고 감성적인"}}
    "레드콤보 신메뉴 12000원이에요"   →  {{"product": "레드콤보",
                                        "situation": "신메뉴 출시", "price": 12000}}
    "레드콤보가 잘 안 팔려서요"       →  {{"product": "레드콤보",
                                        "situation": "판매 부진 만회"}}
    "떡볶이 신메뉴 6000원 매콤하게"   →  {{"product": "떡볶이", "situation": "신메뉴 출시",
                                        "price": 6000, "tone": "매콤한"}}
                                        ← 네 개가 다 들어있으면 네 개를 다 넣는다
    "글쎄요"                         →  {{}}

필수가 아니어도 알아낸 것은 빠짐없이 넣어라.
"""

# 무엇을 물을지는 코드가 정한다(draft.next_slot()). LLM 에게 맡기면
# 이미 답을 받은 걸 또 묻거나, 물어야 할 걸 건너뛴다.
ASK_REQUIRED = """**{label}** 을(를) 물어라. 이건 없으면 광고를 못 만든다.
   다른 건 묻지 마라. 한 번에 하나만.
   말로 설명하기 어려울 때 누를 수 있도록 선택지(options)를 2~4개 함께 줘라."""

ASK_HELPFUL = """**{label}** 을(를) 물어라. 이건 없어도 만들 수는 있지만,
   알면 사장님 마음에 드는 광고가 나온다.
   - 부담 주지 마라. "안 정하셨으면 알아서 만들어드릴게요" 처럼 넘어갈 길을 함께 줘라.
   - 선택지(options)를 2~4개 함께 줘라. 사장님 가게와 상품에 맞는 것으로.
   - 다른 건 묻지 마라."""

WRAP_UP = """물어볼 것을 다 물었다. **더 묻지 말고 마무리해라.**
   "이제 만들어드릴게요" 처럼 알리고 options 는 반드시 빈 배열로 둬라."""

GOAL_LABEL = {"image": "광고 이미지", "copy": "광고 문구"}

# LLM 이 뽑아낼 수 있는 슬롯. goal 은 고정 버튼으로 정해지므로 여기 없다.
_SLOTS = ("product", "price", "situation", "tone", "extra")

SLOT_LABEL = {
    "product": "홍보할 상품·메뉴",
    "price": "가격",
    "situation": "이 광고를 만드는 이유",
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


def _next_action(slot: str | None) -> str:
    if slot is None:
        return WRAP_UP
    template = ASK_REQUIRED if slot in REQUIRED_SLOTS else ASK_HELPFUL
    return template.format(label=SLOT_LABEL[slot])


def _system_prompt(draft: AdBriefDraft, store: Store) -> str:
    return SYSTEM_PROMPT.format(
        industry=store.industry_label,
        store_name=store.name,
        goal=GOAL_LABEL.get(draft.goal or "", "미정"),
        transcript="\n".join(f'- "{t}"' for t in draft.transcript) or "(아직 없음)",
        filled=_describe(draft),
        next_action=_next_action(draft.next_slot()),
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
    # 이번 턴에 무엇을 물을지는 코드가 정하고, LLM 은 그걸 말로 옮기기만 한다.
    asking = draft.next_slot()
    raw = (client or get_client()).complete_json(_system_prompt(draft, store), utterance)

    # 슬롯을 채우기 전에 말부터 기록한다. LLM 이 아무것도 못 뽑아내도
    # 사장님이 한 말은 남아서 문구 생성 프롬프트로 넘어간다.
    merged = draft.with_utterance(utterance).merge(_safe_extract(raw.get("extracted") or {}))
    if asking:
        # 답을 받았는지와 무관하게 물어본 것으로 친다. 안 그러면 사장님이
        # 답을 피할 때 같은 질문을 계속 하게 된다.
        merged = merged.mark_asked(asking)

    options = raw.get("options")
    return ChatTurn(
        message=str(raw.get("message") or "조금 더 자세히 말씀해주시겠어요?"),
        # 더 물을 게 없으면 선택지를 지운다 — LLM 이 지시를 어기고 또 물어봐도
        # 화면에는 안 뜨게 해서 대화가 맴돌지 않게 한다.
        options=(
            [str(o) for o in options]
            if isinstance(options, list) and merged.next_slot() is not None
            else []
        ),
        draft=merged,
    )
