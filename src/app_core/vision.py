"""상품 사진 읽기 — 사진에서 문구에 쓸 만한 것을 뽑아낸다.

사장님이 "그냥 이거 홍보해줘" 하고 사진만 올려도, 사진에 담긴 분위기를
문구가 따라가야 한다. 그러려면 사진을 말로 바꿔놔야 한다.

**여기서 나온 말은 사장님이 한 말이 아니다.** 그래서 tone·situation 슬롯에
넣지 않고 photo_note 라는 별도 자리에 담는다. 슬롯에 섞으면 사장님이 말한
적 없는 값이 주문서에 조용히 들어간다.

사진을 읽는 건 **업로드할 때 한 번**이다. 다시 만들 때마다 부르면 같은 답에
호출비만 더 든다.
"""

from __future__ import annotations

from app_core.llm import VisionClient, get_vision_client

SYSTEM_PROMPT = """너는 상품 사진을 보고, 광고 문구를 쓸 사람에게 넘길 메모를 적는다.

할 일
- **사진에 실제로 보이는 것만** 적어라.
- 맛·가격·재료·원산지·수상 이력은 사진으로 알 수 없다. 절대 적지 마라.
- 사람 얼굴이나 상표가 찍혀 있어도 그건 적지 마라. 상품과 분위기만 본다.
- 무엇인지 모르겠으면 비워라. 억지로 채우지 마라.

적는 것 세 가지
- subject: 사진에 찍힌 것 한 마디. 예) "크로플", "구운 삼겹살", "매장 내부"
- looks: 눈에 띄는 생김새 2~4개. 예) "격자무늬로 바삭하게 구워진 겉면"
- mood: 사진이 주는 분위기 한 마디. 예) "따뜻하고 아늑한", "깔끔하고 차분한"

아래 JSON 형식으로만 답해라.

{ "subject": "...", "looks": ["...", "..."], "mood": "..." }
"""

#: looks 를 몇 개까지 받을지. 많아야 문구 프롬프트만 길어진다.
MAX_LOOKS = 4


def _clean(value: object) -> str:
    return str(value).strip() if isinstance(value, str | int | float) else ""


def format_note(raw: dict) -> str:
    """LLM 응답을 문구 프롬프트에 넣을 몇 줄로 바꾼다.

    구조를 그대로 들고 다니지 않고 문자열로 굳히는 이유: 이 값을 쓰는 곳은
    프롬프트 한 군데뿐이고, DB 에도 한 칸으로 들어간다. 구조가 필요해지면
    그때 모델로 승격하면 된다.
    """
    subject = _clean(raw.get("subject"))
    mood = _clean(raw.get("mood"))
    looks = [t for item in (raw.get("looks") or [])[:MAX_LOOKS] if (t := _clean(item))]

    lines = []
    if subject:
        lines.append(f"- 찍힌 것: {subject}")
    if looks:
        lines.append("- 눈에 띄는 점: " + ", ".join(looks))
    if mood:
        lines.append(f"- 사진의 분위기: {mood}")
    return "\n".join(lines)


def describe(image: bytes, mime: str, client: VisionClient | None = None) -> str:
    """사진에서 읽은 메모. 못 읽으면 빈 문자열.

    실패해도 예외를 올리지 않는다 — 사진 설명은 있으면 좋은 것이지 없다고
    문구를 못 만드는 게 아니다. 사진 한 장 때문에 화면이 죽으면 안 된다.
    """
    try:
        raw = (client or get_vision_client()).read_image(SYSTEM_PROMPT, image, mime)
    except Exception:  # noqa: BLE001 — 통신·응답 파싱 등 무엇이 터져도 문구는 만들어져야 한다
        return ""
    return format_note(raw) if isinstance(raw, dict) else ""
