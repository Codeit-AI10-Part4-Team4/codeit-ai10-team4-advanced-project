"""레퍼런스 이미지 → 분위기 구절 (광고 이미지 만들기 2번).

사장님이 "이런 느낌으로 만들어주세요" 하고 마음에 드는 광고 사진을 올리면,
그 **분위기만** 뽑아 이미지 생성 프롬프트에 얹는다.
실험 근거: notebooks/reference_style_poc.ipynb

## 왜 이미지를 직접 안 넣고 말로 바꾸는가

레퍼런스를 이미지로 넣는 정공법은 둘인데 실험에서 다 탈락했다.

**IP-Adapter** — sd-turbo 에 아예 안 올라간다. cross-attention 차원이 안 맞는다
(sd-turbo 1024 / SD1.5용 768 / SDXL용 2048). 이건 설정 문제가 아니라 구조 문제라
같은 모델을 쓰는 한 방법이 없다.

**img2img** — strength 를 0.9 까지 올려도 **레퍼런스의 상품이 안 없어진다.**
커피 사진을 레퍼런스로 주고 치킨을 주문하면 커피잔이 남는다. 사장님 상품이
안 나오는 것도 문제지만, 그전에 **남의 광고를 복제**하는 것이 된다.

말로 바꾸면 셋 다 해결된다 — 상품은 사장님 것으로 나오고, 베끼지 않고,
GPU 도 안 쓴다. 실험에서 어두운 촛불 분위기가 그대로 옮겨오는 것을 확인했다.

## vision.py 와 나눠 둔 이유

역할이 다르다. `vision.describe()` 는 **제품 사진**을 읽어 **한국어** 메모를
만들고 문구 생성에 쓴다. 여기는 **레퍼런스**를 읽어 **영어** 구절을 만들고
이미지 생성에 쓴다 — 확산 모델이 한국어를 모르기 때문이다
(귀한님 prompt_builder 가 영어를 쓰는 것과 같은 이유).
"""

from __future__ import annotations

from app_core.llm import VisionClient, get_vision_client

#: CLIP 은 77토큰에서 자른다. 뒤가 잘리면 앞의 조건만 살아남으므로 짧게 받는다.
MAX_WORDS = 12

SYSTEM_PROMPT = """You look at a reference advertisement image and write a short
English phrase describing **only its look** — for a text-to-image model.

Rules
- At most 12 words, no quotes, no explanation.
- Describe **lighting, colors, mood, and background/surface** only.
- **Never mention the product, food, object, person, brand, or any text**
  that appears in the image. The user is advertising something else entirely;
  naming what you see would put someone else's product into their ad.
- If you cannot tell, use an empty string.

Answer in JSON only, in this exact shape:

{ "phrase": "warm golden light, rustic wooden surface, soft shadows, cozy mood" }

Bad phrase: "a cup of coffee on a wooden table"   ← names the product
"""


def _clean(text: str) -> str:
    """모델이 따옴표·마침표를 붙여 보내는 경우가 있어 벗겨낸다."""
    return text.strip().strip('"').strip().rstrip(".")


def describe_style(image: bytes, mime: str, client: VisionClient | None = None) -> str:
    """레퍼런스에서 분위기 구절을 뽑는다. 못 읽으면 빈 문자열.

    실패해도 예외를 올리지 않는다 — 레퍼런스는 있으면 좋은 것이지 없다고
    광고를 못 만드는 게 아니다. vision.describe() 와 같은 원칙이다.
    """
    try:
        raw = (client or get_vision_client()).read_image(SYSTEM_PROMPT, image, mime)
    except Exception:  # noqa: BLE001 — 통신·파싱 무엇이 터져도 생성은 계속돼야 한다
        return ""
    if not isinstance(raw, dict):
        return ""

    # read_image 는 JSON 을 돌려주므로 어느 키에 담기든 문자열 하나를 건져 쓴다.
    for value in raw.values():
        if isinstance(value, str) and (text := _clean(value)):
            return " ".join(text.split()[:MAX_WORDS])
    return ""


def apply_to(prompt: str, style: str) -> str:
    """생성 프롬프트에 분위기를 얹는다.

    **뒤에 붙인다.** CLIP 이 77토큰에서 자를 때 상품·구도 같은 핵심 조건이
    먼저 살아남아야 한다 — 잘려서 없어져도 되는 건 분위기 쪽이다.
    """
    return f"{prompt}, {style}" if style else prompt
