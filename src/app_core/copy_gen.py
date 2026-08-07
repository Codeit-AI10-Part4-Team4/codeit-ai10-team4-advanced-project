"""광고 문구 생성 — 후보 3건.

헤드라인과 서브를 나눠서 낸다. 이미지에 얹을 때 헤드라인은 크게, 서브는 작게
배치해야 하는데 한 덩어리로 주면 이미지 담당이 어디서 자를지 알 수 없다.

가격은 사장님이 입력한 값만 쓴다. 0 원이면 광고에 가격을 넣지 않는다 —
없는 가격을 쓰면 표시광고법 위반이다.
"""

from __future__ import annotations

from pydantic import ValidationError

from app_core.llm import ChatClient, get_client
from app_core.schema import AdBrief, CopyCandidate, Store

CANDIDATE_COUNT = 3
MAX_HEADLINE = 20
MAX_SUB = 40

SYSTEM_PROMPT = """너는 동네 가게 광고 문구를 쓰는 카피라이터다.

가게
- 업종: {industry}
- 상호: {store_name}

이번 광고
- 홍보 대상: {product}
- 알리려는 것: {situation}
- 원하는 느낌: {tone}
- 그 밖의 요청: {extra}
{price_line}
{transcript}{history}
규칙
- **{count}개**를 서로 다르게 만들어라.
- 헤드라인은 {max_headline}자 이내, 서브는 {max_sub}자 이내.
- **주어진 사실만 써라.** 가격·재료·수상 이력 등 위에 없는 내용을 지어내지 마라.
- "최고", "1위" 같은 표현은 근거가 없으면 쓰지 마라.
{sub_rule}

아래 JSON 형식으로만 답해라.

{{ "candidates": [ {{ "headline": "...", "sub": "..." }} ] }}
"""


def _price_line(brief: AdBrief) -> str:
    if brief.show_price:
        return f"- 가격: {brief.price:,}원 (이 금액 그대로만 써라)"
    return "- 가격: **문구에 가격을 넣지 마라.** 사장님이 가격 없이 만들기를 원한다."


def _history_block(recent: list[AdBrief]) -> str:
    if not recent:
        return ""
    lines = [f"- {a.product} ({a.situation or '홍보'}, {a.tone or '기본'})" for a in recent]
    return "이 가게가 전에 만든 광고 (겹치지 않게 참고만):\n" + "\n".join(lines) + "\n"


def _transcript_block(brief: AdBrief) -> str:
    """사장님이 한 말 원문.

    위의 항목들은 이 말에서 뽑아낸 요약이라 뉘앙스가 깎여 있다.
    "단골분들이 매콤한 걸 좋아하셔서" 같은 말은 어느 항목에도 안 들어가지만
    문구를 쓸 때 가장 쓸모 있다.
    """
    if not brief.transcript:
        return ""
    lines = "\n".join(f'- "{t}"' for t in brief.transcript)
    return (
        "\n사장님이 한 말 (원문 — 위 항목이 놓친 것을 여기서 읽어라):\n"
        f"{lines}\n"
        "⚠️ 여기 있는 말도 사장님이 직접 한 말이지만, "
        "없는 사실을 상상해서 채우지는 마라.\n"
    )


def _system_prompt(brief: AdBrief, store: Store, recent: list[AdBrief]) -> str:
    return SYSTEM_PROMPT.format(
        industry=store.industry_label,
        store_name=store.name,
        product=brief.product,
        situation=brief.situation or "(없음)",
        tone=brief.tone or "(없음)",
        extra=brief.extra or "(없음)",
        price_line=_price_line(brief),
        transcript=_transcript_block(brief),
        history=_history_block(recent),
        count=CANDIDATE_COUNT,
        max_headline=MAX_HEADLINE,
        max_sub=MAX_SUB,
        sub_rule=(
            "- 서브 문구도 함께 만들어라."
            if brief.with_sub
            else '- 헤드라인만 만들고 sub 는 ""로 비워라.'
        ),
    )


def generate(
    brief: AdBrief,
    store: Store,
    recent: list[AdBrief] | None = None,
    client: ChatClient | None = None,
) -> list[CopyCandidate]:
    """문구 후보를 만든다. 형식이 깨진 후보는 버리고 나머지만 돌려준다."""
    raw = (client or get_client()).complete_json(
        _system_prompt(brief, store, recent or []),
        f"{store.name}의 {brief.product} 광고 문구를 만들어줘.",
    )

    candidates = []
    for item in raw.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        try:
            candidate = CopyCandidate(
                headline=str(item.get("headline", ""))[:MAX_HEADLINE],
                sub=str(item.get("sub", ""))[:MAX_SUB] if brief.with_sub else "",
            )
        except ValidationError:
            continue  # 헤드라인이 비었다 — 쓸 수 없는 후보
        candidates.append(candidate)
    return candidates[:CANDIDATE_COUNT]
