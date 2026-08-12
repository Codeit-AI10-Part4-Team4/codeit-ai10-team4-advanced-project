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

from app_core import turnlog
from app_core.llm import ChatClient, get_client
from app_core.schema import REQUIRED_SLOTS, AdBriefDraft, ChatTurn, Store

SYSTEM_PROMPT = """너는 동네 가게 사장님이 광고를 만들도록 돕는 챗봇이다.

가게: {industry} · {store_name}
사장님이 만들려는 것: {goal}

# 사장님이 지금까지 한 말
{transcript}

# 이미 알고 있는 것 (참고용)
{filled}
⚠️ 이건 **지난 턴까지** 알아낸 것이다. 이번 말이 이걸 **고치는 말**일 수 있다.
   "아니 6000원이요"·"말고 ○○요"·"○○ 아니고 ○○" → **새 값으로 바꿔서** extracted 에 넣어라.
   위 값을 그대로 두면 사장님이 고쳐달라고 한 게 무시된다.

# 할 일 — 순서대로
1. 사장님의 **이번 말**에서 새로 알아낸 것을 extracted 에 넣는다.
   ⚠️ 이걸 먼저 해라. 물어볼 생각부터 하면 답이 눈앞에 있는데도 되묻게 된다.
2. 아래는 **이번 말을 듣기 전** 기준으로 아직 모르는 것이다. 우선순위 순.
     {unknown}
   여기서 **이번 말로 알아낸 것을 빼고** 남는 것을 `still_unknown` 에 적어라.
   머릿속으로만 하지 말고 반드시 적어라. 안 적으면 이미 답한 걸 또 묻게 된다.
   ⚠️ **1번에서 extracted 에 넣은 항목은 반드시 빼라.** 그게 이번 말로 받은 답이다.
      extracted 에 price 를 넣었으면 still_unknown 에 "가격"이 있으면 안 된다.

3. `still_unknown` 이 **비었으면** `ask_about` 을 빈 문자열로 두고 질문하지 마라.
   "이제 만들어드릴게요" 하고 끝내라. options 도 빈 배열.

4. 비지 않았으면 `still_unknown` 의 **맨 위 항목을 `ask_about` 에 적어라.**
   그리고 **`ask_about` 에 적은 것만** 물어라. 다른 걸 물으면 안 된다.
   ⚠️ 사장님 말에 다른 항목이 언급됐더라도 순서를 바꾸지 마라.
      "뭘 원하는 느낌이야" 라고 되물어도, 맨 위가 가격이면 **가격을 물어라.**

   맨 위 항목을 물을 때는 이렇게 물어라 —
   {next_action}

   ⚠️ 위 안내도 **이번 말을 듣기 전** 기준으로 쓰인 것이다. 이번 말로 그 항목의
      답을 이미 받았다면 저 안내를 따르지 말고, `still_unknown` 의 맨 위를 물어라.
      **방금 답을 받은 것을 다시 묻는 것이 가장 나쁘다.**

# extracted 규칙 — 가장 중요하다
- **이번 말에서 새로 알아낸 것만** 넣어라. 이미 알고 있는 것을 되풀이해 넣지 마라.
- 한 문장에 여러 개가 들어 있으면 **빠짐없이 전부** 넣어라. 하나만 넣고 끝내지 마라.
- 홍보할 대상을 말하면 product 에 넣어라.
    "크로플 홍보하고싶어"  →  product: "크로플"
    "레드콤보요"           →  product: "레드콤보"
  **정중하게 부탁하는 말에서도 찾아라.** 짧은 말만 알아듣는 게 아니다.
    "레드콤보를 홍보할만한 문구를 작성해줘"  →  product: "레드콤보"
    "아메리카노 광고 좀 부탁드려요"          →  product: "아메리카노"
    "크로플 알릴 만한 거 하나 만들어주세요"   →  product: "크로플"
  ⚠️ **"문구"·"광고"·"홍보물"·"이미지" 는 상품명이 아니다.** 그건 사장님이
     만들어달라는 것이지 파는 물건이 아니다.
  ⚠️ **가게 이름도 상품명이 아니다.** 위 "가게" 에 이미 적혀 있다.
    "교촌치킨 레드콤보를 홍보해줘"  →  product: "레드콤보" (교촌치킨 아님)
  **할인·행사 문장에도 상품이 들어 있다.** "반값"·"두 판 사면" 같은 말에
  정신이 팔려 상품명을 놓치지 마라.
    "이번 주만 아메리카노 반값이에요"  →  product: "아메리카노", situation: "할인"
    "피자 두 판 사면 콜라 줘요"        →  product: "피자", situation: "사은 행사"
  ⚠️ **상품명은 "무엇을 파는지" 다.** 아래는 상품명이 아니라 situation 이다.
     "신메뉴"  "할인"  "이벤트"  "행사"  "특가"  "세일"
     메뉴 이름을 못 찾았으면 product 를 **비워라.** 억지로 채우지 마라.
     "이번에 낸 신메뉴예요" → product 없음, situation: "신메뉴 출시"
  ⚠️ **메뉴 이름 옆에 그런 말이 붙어 있으면 둘 다 넣어라.** 하나만 넣고 끝내지 마라.
     "레드콤보 신메뉴인데"  →  product: "레드콤보" **그리고** situation: "신메뉴 출시"
     "아메리카노 특가예요"  →  product: "아메리카노" **그리고** situation: "특가"
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
        **가격을 넣지 말라는 뜻이면 표현이 달라도 전부 ② 다.**
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

# 말투 — 짧게, 하나만
사장님은 광고 전문가가 아니고 폰으로 본다. 길면 안 읽는다.

- **한 문장, 30자 안쪽.**
- **물음표는 하나만.** "~인가요? ~인가요?" 처럼 두 번 묻지 마라.
- **"사장님" 호칭을 매번 붙이지 마라.** 이미 사장님인 걸 안다.
- **사장님이 한 말을 되풀이하지 마라.** 확인 문장을 앞에 붙이지 마라.
    나쁨: "가격을 4500원으로 정하셨군요! 혹시 더 추가할 내용이 있으신가요?"
    나쁨: "이 광고를 만드는 이유가 신메뉴 출시라면 좋겠네요. 원하는 느낌은?"
    → 앞의 확인을 **통째로 버리고** 물어볼 것만 남겨라.
- 인사말·감탄사로 시작하지 마라. 바로 물어라.
- ⚠️ 위 규칙은 **길이와 말투**에 대한 것이다. **무엇을 물을지는 「할 일」 2번이 정한다.**
  거기 적힌 항목을 물어라. 매번 같은 것을 묻지 마라.

아래 JSON 형식으로만 답해라.

**순서를 지켜라.** extracted → still_unknown → ask_about → message → options.
앞의 것을 쓰지 않고 message 부터 쓰면 이미 답한 것을 또 묻거나 엉뚱한 걸 묻게 된다.

⚠️ 아래는 **자리를 보여주는 틀**이다. 안에 적힌 말을 값으로 베끼지 마라.
   특히 `still_unknown` 과 `ask_about` 은 위 「할 일」 2·3번에서 **직접 계산한
   결과**를 적는 자리다. 다 알아냈으면 `[]` 와 `""` 다.

{{
  "extracted": {{"product": "...", "price": 숫자, "situation": "...", "tone": "...", "extra": "..."}},
  "still_unknown": ["아직 모르는 것을 우선순위 순으로", "..."],
  "ask_about": "위 목록의 맨 위 하나. 목록이 비었으면 빈 문자열",
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
   - **{label} 만 물어라.** 다른 건 묻지 마라.
   - **선택지(options)를 2~4개 반드시 줘라.** 말로 설명하기 어려운 사장님이 누른다.
     빈 배열로 두지 마라."""

ASK_HELPFUL = """**{label}** 을(를) 물어라. 이건 없어도 만들 수는 있지만,
   알면 사장님 마음에 드는 광고가 나온다.
   - **무엇을 묻는지 분명히 해라.** "더 필요한 게 있나요" 처럼 두루뭉술하게
     물으면 사장님이 무슨 답을 해야 할지 모른다.
   - 부담 주지 마라. 선택지 안에 "알아서 해주세요" 같은 빠져나갈 길을 하나 둬라.
   - **선택지(options)를 2~4개 반드시 줘라.** 사장님 가게와 상품에 맞는 것으로.
     빈 배열로 두지 마라.
   - 다른 건 묻지 마라."""

WRAP_UP = """물어볼 것을 다 물었다. **더 묻지 마라.**
   - `still_unknown` 은 `[]`, `ask_about` 은 `""`, options 는 빈 배열.
   - message 는 짧게 마무리만. **질문으로 끝내지 마라.**
     사장님은 이미 할 말을 다 했다.
   - 이번 말이 값을 **고치는 말**일 수 있으니 extracted 는 계속 채워라."""

#: 더 물을 게 없을 때 하는 말. LLM 이 아니라 코드가 쓴다 — 아래 respond() 참고.
DONE_MESSAGE = "필요한 건 다 여쭤봤어요. 이제 만들어드릴게요."

#: LLM 이 message 를 안 준 경우
FALLBACK_MESSAGE = "조금 더 자세히 말씀해주시겠어요?"

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


def _unknown(draft: AdBriefDraft) -> str:
    """아직 모르는 것 전부. 하나만 주면 사장님이 그걸 이미 답해버렸을 때
    LLM 이 다음에 무엇을 물어야 할지 몰라 엉뚱한 걸 묻는다.
    """
    left = draft.remaining_slots()
    if not left:
        return "(없음 — 다 알았다)"
    return "\n     ".join(f"{i}. {SLOT_LABEL[s]}" for i, s in enumerate(left, start=1))


def _system_prompt(draft: AdBriefDraft, store: Store) -> str:
    return SYSTEM_PROMPT.format(
        industry=store.industry_label,
        store_name=store.name,
        goal=GOAL_LABEL.get(draft.goal or "", "미정"),
        transcript="\n".join(f'- "{t}"' for t in draft.transcript) or "(아직 없음)",
        filled=_describe(draft),
        next_action=_next_action(draft.next_slot()),
        unknown=_unknown(draft),
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

    # 실제 발화로 골든셋을 채우려고 남긴다. 실패해도 대화는 계속된다.
    turnlog.record(utterance, draft, merged, asking, store.industry_label)

    # 더 물을 게 없으면 **말도 코드가 쓴다.** 무엇을 물을지를 코드가 정하는 것과
    # 같은 이유다 — 여기서 LLM 에게 맡기면 지시를 어기고 이미 답한 것을 또 묻는다.
    #
    # 실제로 그랬다: 프롬프트 아래쪽 JSON 틀에 예시로 적어둔 "가격"·"원하는 느낌"
    # 을 그대로 베껴서, 다 채워진 뒤에도 그 둘을 번갈아 물었다. 마무리 인사는
    # 한 줄이라 LLM 이 필요 없고, 코드가 쓰면 이 실패가 아예 불가능해진다.
    if merged.next_slot() is None:
        return ChatTurn(message=DONE_MESSAGE, options=[], draft=merged)

    options = raw.get("options")
    return ChatTurn(
        message=str(raw.get("message") or FALLBACK_MESSAGE),
        options=[str(o) for o in options] if isinstance(options, list) else [],
        draft=merged,
    )
