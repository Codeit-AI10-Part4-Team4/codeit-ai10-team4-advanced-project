"""광고 문구 생성 — 후보 3건.

헤드라인과 서브를 나눠서 낸다. 이미지에 얹을 때 헤드라인은 크게, 서브는 작게
배치해야 하는데 한 덩어리로 주면 이미지 담당이 어디서 자를지 알 수 없다.

가격은 사장님이 입력한 값만 쓴다. 0 원이면 광고에 가격을 넣지 않는다 —
없는 가격을 쓰면 표시광고법 위반이다.

다시 만들 때는 직전 결과와 피드백을 프롬프트에 얹는다. 조건(상품·가격)은
그대로 두므로, 결과가 마음에 들 때까지 대화를 처음부터 다시 하지 않아도 된다.
"""

from __future__ import annotations

import re

from pydantic import ValidationError

from app_core.llm import ChatClient, get_client
from app_core.schema import AdBrief, CopyCandidate, Store

CANDIDATE_COUNT = 3
#: LLM 에게는 더 많이 시킨다. 길이를 어긴 후보와 수량을 오인한 후보를 버리고
#: 나면 셋이 안 남는다. **행사와 가격이 같이 있는 주문**이 특히 심하다 —
#: "2+1 · 한 캔 2,000원" 에서 5건을 시켰는데 화면에 1건만 남은 적이 있다.
#: 고를 게 하나뿐이면 "골라 보세요" 가 성립하지 않는다.
ASK_COUNT = 8
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
    """가격 한 줄 — **무엇의 금액인지**까지 못박는다.

    금액만 주면 모델이 바로 위의 "광고를 만드는 이유" 와 붙여 버린다. 실제로
    이유가 "2 + 1 이벤트" 이고 가격이 2,000원(한 캔 값)일 때 **"2+1 이벤트
    2,000원"** 이 나왔다 — 세 캔을 2,000원에 준다는 뜻이 되는 오인 광고다.

    금액 자체는 맞아서 가격 검사(eval/copy_metrics.price_violations)도 통과한다.
    틀린 건 금액이 아니라 "무엇의 금액인가" 라서, 문장으로 고정하는 수밖에 없다.
    """
    if not brief.show_price:
        return "- 가격: **문구에 가격을 넣지 마라.** 사장님이 가격 없이 만들기를 원한다."
    # ⚠️ 아래 예시에 **이번 광고의 금액·상품을 쓰지 마라.** 한 번 그렇게 썼더니
    # 모델이 나쁜 예시(X)를 그대로 베껴서 문구로 내놨다 — 챗봇에서 JSON 틀의
    # 예시가 값으로 복사됐던 것과 같은 실패다. 예시는 항상 딴 가게 숫자로 든다.
    return (
        f"- 가격: {brief.price:,}원 — **{brief.product} 한 개 값이다.**\n"
        "  ⚠️ **금액과 개수를 짝지어 쓰려면 사장님이 그 짝을 그대로 말했어야 한다.**\n"
        "     한 개 값을 여러 개에 붙이면 사장님이 말한 적 없는 조건이 된다.\n"
        '       X "1+1 행사 3,000원"     ← 한 개 값을 두 개 값처럼 말했다\n'
        '       X "3,000원에 2잔"        ← 짝지은 적 없는 개수를 붙였다\n'
        '       O "아메리카노 3,000원"   ← 행사는 금액과 떼어서 적는다\n'
        "  ⚠️ 개수를 곱하거나 나눠서 **네가 금액을 만들지 마라.**\n"
        "  ⚠️ 행사 내용을 **네가 풀어 설명하지 마라.** 사장님이 쓴 말 그대로 적어라 —\n"
        '     "1+1" 을 "한 잔 값에 두 잔" 처럼 바꾸면 조건이 달라진다.\n'
        "  ✅ 행사와 금액을 같이 알리려면 **이 모양으로** 써라 —\n"
        '       "1+1 행사 · 아메리카노 한 잔 3,000원"\n'
        "     행사 표기는 사장님이 쓴 그대로, 금액은 **한 개에만** 붙인다."
    )


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
    # 조건(가격·상품)은 재생성 때 그대로 넘어온다(AdBrief.revised). 그래서 사장님이
    # "그 가격이 아니라 3캔에 4,000원" 처럼 **바로잡는 말**을 하면 위의 가격 줄과
    # 정면으로 부딪히고, "이 금액 그대로만 써라" 쪽이 이겨서 문구가 그대로였다.
    # 방금 한 말이 지난 턴의 조건보다 나중이므로 여기서 우선순위를 정해준다.
    parts.append(
        "\n→ 위 지적을 **반드시 반영**해라. 이건 사장님이 **방금** 하신 말이라\n"
        "   위의 조건보다 우선한다. 금액을 바로잡아 주셨으면 **그 금액을 써라** —\n"
        "   위 가격 줄과 달라도 방금 하신 말이 맞다.\n"
        "   ⚠️ 단 **사장님이 직접 말한 금액만** 쓸 수 있다. 네가 계산하지 마라.\n"
        "   그 밖에 없는 사실은 여전히 지어내지 마라.\n"
    )
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
        count=ASK_COUNT,
        max_headline=MAX_HEADLINE,
        max_sub=MAX_SUB,
        sub_rule=(
            "- 서브 문구도 함께 만들어라."
            if brief.with_sub
            else '- 헤드라인만 만들고 sub 는 ""로 비워라.'
        ),
    )


# ── 수량 오인 거르기 ────────────────────────────────────────────
#
# 금액과 개수를 붙여 쓰면 사장님이 말한 적 없는 조건이 만들어진다. 한 캔 2,000원
# 인 카스에 "2 + 1 이벤트" 를 얹었더니 **"2,000원에 2+1으로 만나요"** 가 나왔다 —
# 세 캔을 2,000원에 준다는 뜻이다. 금액 자체는 맞아서 가격 검사로는 안 잡힌다.
#
# 프롬프트로 세 번 막아봤지만(한 개 값이라고 명시 · 나쁜 예시 · 풀어쓰기 금지)
# 후보 셋 중 둘이 계속 샜다. 그래서 **코드가 거른다** — 길이를 어긴 후보를
# 버리는 것과 같은 자리다. 프롬프트는 그대로 두는데, 잘 나올 때는 잘 나오고
# 거르는 쪽은 잘못 나온 것만 버리기 때문이다.

_UNITS = "개|잔|캔|병|판|장|줄|팩|인분|봉지|세트|박스|마리"
_HANGUL = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8}
_QTY_NUM = re.compile(rf"(\d+)\s*(?:{_UNITS})")
_QTY_HANGUL = re.compile(rf"({'|'.join(_HANGUL)})\s*(?:{_UNITS})")
#: "2+1" · "1 + 1" — 행사 표기.
#:
#: 🪤 이 숫자를 **개수 주장으로 세면 안 된다.** 전에 그렇게 했더니 "2+1" 이
#: "2개도 3개도 말한 것" 으로 인정돼서, `"한 캔에 2000원으로 두 캔"` 같은 문구가
#: 통과했다 (2+1 은 **두 캔 값에 세 캔**이다). 반대로 개수로 안 세면
#: `"2+1 행사, 한 캔 2,000원"` 같은 멀쩡한 문구도 안 걸린다.
#: 행사 표기는 개수와 따로 두고, **사장님이 쓴 표기 그대로인지**만 본다.
_EVENT = re.compile(r"(\d+)\s*\+\s*(\d+)")
#: 금액. 만·천 단위를 붙여 쓴 것까지 한 덩어리로 읽는다 ("1만 5천원" → 15000)
_MONEY = re.compile(r"(?:(\d[\d,]*)\s*만)?\s*(?:(\d[\d,]*)\s*천)?\s*(\d[\d,]*)?\s*원")

#: 금액과 개수가 이만큼 안에 붙어 있으면 "그 개수가 그 금액" 이라는 주장으로 본다.
#: 넓히면 "한 캔 2,000원, 3캔 4,000원" 처럼 짝이 둘인 문장에서 엉뚱한 짝이 생긴다.
_NEAR = 12


def _won(man: str, cheon: str, rest: str) -> int:
    def digits(part: str) -> int:
        return int(part.replace(",", "")) if part else 0

    return digits(man) * 10_000 + digits(cheon) * 1_000 + digits(rest)


def _money_spans(text: str) -> list[tuple[int, int]]:
    """(위치, 금액) 목록."""
    out = []
    for m in _MONEY.finditer(text):
        if any(m.groups()):
            out.append((m.start(), _won(*m.groups())))
    return out


def _qty_spans(text: str) -> list[tuple[int, int]]:
    """(위치, 개수) 목록. **단위가 붙은 것만** 개수로 센다 — 행사 표기는 뺀다."""
    out = [(m.start(), int(m.group(1))) for m in _QTY_NUM.finditer(text)]
    out += [(m.start(), _HANGUL[m.group(1)]) for m in _QTY_HANGUL.finditer(text)]
    return out


def _events(text: str) -> set[tuple[int, int]]:
    """행사 표기 그대로. "2+1" 을 "1+1" 로 바꿔 쓰면 조건이 달라진다."""
    return {(int(a), int(b)) for a, b in _EVENT.findall(text)}


#: (개수, 금액↔개수 짝, 행사 표기)
Claims = tuple[set[int], set[tuple[int, int]], set[tuple[int, int]]]


def _spans(text: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(금액 목록, 개수 목록).

    금액에 **가장 가까운 것이 행사 표기**면 그 금액이 묶음 값처럼 읽힌다 —
    `"2,000원에 2+1으로 만나요"` 는 세 캔을 2,000원에 준다는 뜻이 된다. 그럴
    때만 행사의 숫자를 **개수 주장으로 올린다.** 개수가 더 가까이 있으면
    (`"2+1 행사, 한 캔 2,000원"`) 금액은 그 개수에 붙은 것이라 올리지 않는다.
    """
    money = _money_spans(text)
    qty = _qty_spans(text)
    promoted = []
    for m in _EVENT.finditer(text):
        for mpos, _ in money:
            gap = abs(mpos - m.start())
            if gap > _NEAR or any(abs(mpos - pq) < gap for pq, _ in qty):
                continue
            promoted += [(m.start(), int(m.group(1))), (m.start(), int(m.group(2)))]
            break
    return money, qty + promoted


def _claims(text: str) -> Claims:
    """**문구**가 주장하는 것.

    금액 하나에 **가장 가까운 개수 하나**만 짝짓는다. 가까운 것 전부를 짝지으면
    "한 캔에 2,000원, 3캔에 4,000원" 처럼 짝이 둘인 짧은 문장에서 2,000원과 3캔이
    이웃해 버려, 사장님이 그대로 말한 문구가 오인으로 걸린다.
    """
    money, qty = _spans(text)
    pairs = set()
    for pos, amount in money:
        near = [(abs(pos - pq), q) for pq, q in qty if abs(pos - pq) <= _NEAR]
        if not near:
            continue
        closest = min(d for d, _ in near)
        pairs |= {(amount, q) for d, q in near if d == closest}
    return {q for _, q in qty}, pairs, _events(text)


def _said_claims(text: str) -> Claims:
    """**사장님 말**에서 읽는 같은 것 — 이쪽은 넉넉하게 본다.

    근거를 좁게 잡으면 멀쩡한 문구가 걸린다. 사장님이 한 말이라 넓게 인정해도
    없는 사실이 되지 않으므로, 가까이 있는 짝은 전부 근거로 친다.
    """
    money, qty = _spans(text)
    pairs = {(a, q) for pa, a in money for pq, q in qty if abs(pa - pq) <= _NEAR}
    return {q for _, q in qty}, pairs, _events(text)


def _grounds(brief: AdBrief) -> Claims:
    """사장님이 실제로 한 수량 주장.

    가격 슬롯은 **상품 한 개 값**이므로 "1개 = price원" 을 근거에 넣어준다.
    안 넣으면 "카스 한 잔 2,000원" 같은 **맞는** 문구까지 걸러진다.
    """
    said = [*brief.transcript]
    said += [s for s in (brief.situation, brief.extra) if s]
    if brief.feedback:
        said += brief.feedback.notes
    if brief.show_price:
        said.append(f"{brief.product} 1개 {brief.price}원")

    qty: set[int] = set()
    pairs: set[tuple[int, int]] = set()
    events: set[tuple[int, int]] = set()
    for line in said:
        q, p, e = _said_claims(line)
        qty |= q
        pairs |= p
        events |= e
    return qty, pairs, events


def _misleading(text: str, grounds: Claims) -> bool:
    """사장님이 하지 않은 수량 주장이 들어 있으면 True.

    ① 말한 적 없는 개수      "2000원으로 두 캔" — 사장님은 한 캔 값만 말했다
    ② 말한 적 없는 금액↔개수  "2,000원에 3캔"   — 3캔은 4,000원이라고 하셨다
    ③ 바꿔 쓴 행사 표기      "1+1"            — 사장님은 2+1 이라고 하셨다
    """
    said_qty, said_pairs, said_events = grounds
    qty, pairs, events = _claims(text)
    return not (qty <= said_qty and pairs <= said_pairs and events <= said_events)


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

    grounds = _grounds(brief)
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

        # 헤드라인과 서브를 **따로** 본다. 이어 붙여서 보면 서로 멀리 있던
        # 금액과 개수가 붙은 것처럼 읽혀 멀쩡한 후보가 걸린다.
        if any(_misleading(part, grounds) for part in (headline, sub) if part):
            continue

        try:
            candidate = CopyCandidate(headline=headline, sub=sub)
        except ValidationError:
            continue  # 헤드라인이 비었다 — 쓸 수 없는 후보
        candidates.append(candidate)
    return candidates[:CANDIDATE_COUNT]
