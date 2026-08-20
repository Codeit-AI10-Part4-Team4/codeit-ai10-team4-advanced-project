"""광고 문구 생성 — 후보 3건.

헤드라인과 서브를 나눠서 낸다. 이미지에 얹을 때 헤드라인은 크게, 서브는 작게
배치해야 하는데 한 덩어리로 주면 이미지 담당이 어디서 자를지 알 수 없다.

가격은 사장님이 입력한 값만 쓴다. 0 원이면 광고에 가격을 넣지 않는다 —
없는 가격을 쓰면 표시광고법 위반이다.

다시 만들 때는 직전 결과와 피드백을 프롬프트에 얹는다. 조건(상품·가격)은
그대로 두므로, 결과가 마음에 들 때까지 대화를 처음부터 다시 하지 않아도 된다.
"""

from __future__ import annotations

from pydantic import ValidationError

from app_core.llm import ChatClient, get_client
from app_core.schema import AdBrief, CopyCandidate, Store

CANDIDATE_COUNT = 3
MAX_HEADLINE = 20
MAX_SUB = 40

#: 다시 만들기 선택지. 말로 설명하기 어려운 사장님이 누른다.
#: 대화 중 선택지와 달리 LLM 이 만들지 않는다 — 고칠 방향은 업종·상품과
#: 무관하게 비슷해서(길이·세기·강조점) 매번 새로 만들 이유가 없다.
REVISION_OPTIONS = (
    "더 짧게",
    "더 힘있게",
    "더 부드럽게",
    "가격을 강조해서",
    "아예 다른 느낌으로",
)

SYSTEM_PROMPT = """너는 동네 가게 광고 문구를 쓰는 카피라이터다.

가게
- 업종: {industry}
- 상호: {store_name}

이번 광고
- 홍보 대상: {product}
- 광고를 만드는 이유: {situation}
- 원하는 느낌: {tone}
- 그 밖의 요청: {extra}
{price_line}
{transcript}{photo}{revision}{history}
규칙
- **{count}개**를 서로 다르게 만들어라.
- 헤드라인은 {max_headline}자 이내, 서브는 {max_sub}자 이내.
{sub_rule}

**광고는 사실을 말해야 한다. 위에 없는 것은 지어내지 마라.**
확인할 수 없는 특징(재료·품질·맛·수상·인증·원산지·인기)은 업종에서 당연해 보여도
추론하면 안 된다 — 사실과 다른 광고가 된다.

  X "신선한 재료로 만든"   X "최고급 원두"   X "정성 가득"   X "소문난 맛집"
  X "국산만 고집합니다"    X "최고의 한 점"   X "수제"       X "전통 방식"

위에 사장님이 그렇게 말한 것이 있다면 그때는 써도 된다.

**할 말이 부족하면 분위기로 써라.** 빈자리를 없는 사실로 채우지 마라.
분위기는 창작해도 되지만 **분위기 문구에도 사실을 주장하면 안 된다.**

  O "천천히 머무는 오후"     X "최고의 원두로 내린 커피"
  O "퇴근길에 한 잔"        X "매일 신선한 재료로 굽습니다"

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


def _photo_block(brief: AdBrief) -> str:
    """사장님이 올린 상품 사진에서 읽은 것.

    사진을 올렸다는 건 "이런 느낌으로 만들어줘"라는 뜻이다. 말로 못 하는
    분위기가 사진엔 담겨 있어서, 여기를 참고하면 톤이 상품과 따로 놀지 않는다.

    말과 구분해서 넣는 이유: 이건 모델이 사진을 보고 적은 것이라 사장님 말보다
    믿을 만하지 않다. 섞어 놓으면 사장님이 하지도 않은 말이 근거가 된다.
    """
    if not brief.photo_note:
        return ""
    return (
        "\n사장님이 올린 상품 사진에서 읽은 것:\n"
        f"{brief.photo_note}\n"
        "⚠️ 이건 사진을 보고 적은 메모지 사장님이 한 말이 아니다. 분위기를 잡는 데만"
        " 참고하고, 여기 없는 맛·재료·가격은 지어내지 마라.\n"
    )


FEEDBACK_LABEL = {
    "typed": "사장님이 이렇게 고쳐달라고 하셨다",
    "option": "사장님이 이렇게 고쳐달라고 하셨다",
    "panel": "AI 손님 패널이 평가한 결과다",
}


def _revision_block(brief: AdBrief) -> str:
    """다시 만드는 경우에만 붙는다.

    직전 결과를 보여주는 이유는 두 가지다 — 같은 걸 또 내놓지 않게,
    그리고 무엇을 고치라는 말인지 알 수 있게.
    """
    if brief.feedback is None:
        return ""

    parts = ["\n## 다시 만드는 중이다"]
    if brief.prev_copies:
        made = "\n".join(
            f"- {c.headline}" + (f" / {c.sub}" if c.sub else "") for c in brief.prev_copies
        )
        parts.append(f"\n직전에 만든 문구 (이것과 **다르게** 만들어라):\n{made}")

    fb = brief.feedback
    notes = "\n".join(f"- {n}" for n in fb.notes)
    parts.append(f"\n{FEEDBACK_LABEL[fb.source]}:\n{notes}")
    if fb.resistance:
        parts.append("\n손님들이 걸린 부분: " + ", ".join(fb.resistance))
    parts.append("\n→ 위 지적을 **반드시 반영**해라. 그래도 없는 사실은 지어내지 마라.\n")
    return "\n".join(parts)


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
        photo=_photo_block(brief),
        revision=_revision_block(brief),
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
        headline = str(item.get("headline", "")).strip()
        sub = str(item.get("sub", "")).strip() if brief.with_sub else ""

        # 길이를 어긴 후보는 **자르지 않고 버린다.** 잘라서 내보내면
        # "신메뉴 크로플 출시 기념 특가 이벤" 처럼 중간에서 끊긴 문구가
        # 사장님 화면에 그대로 뜬다. 후보는 하나씩 따로 판단하므로 긴 것
        # 하나 때문에 나머지가 같이 죽지는 않는다.
        if len(headline) > MAX_HEADLINE or len(sub) > MAX_SUB:
            continue
        try:
            candidate = CopyCandidate(headline=headline, sub=sub)
        except ValidationError:
            continue  # 헤드라인이 비었다 — 쓸 수 없는 후보
        candidates.append(candidate)
    return candidates[:CANDIDATE_COUNT]
