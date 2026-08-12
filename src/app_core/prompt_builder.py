"""프롬프트 부품 — 한국어 주문 정보를 배경 생성용 영어 프롬프트로 바꾼다.

배경 생성 모델(sd 계열)이 한국어를 이해하지 못해서 이 번역 단계가 필요하다.
실험 근거: notebooks/background_gen_poc.ipynb (한글 프롬프트 → 엉뚱한 그림)
"""

from openai import OpenAI

# 어떤 주문이 와도 공통으로 지킬 조건 — 제품을 놓을 "빈 탁자"가 앞에 있어야 한다.
# 실험 근거: 같은 seed 로 3안 비교(notebooks/background_gen_poc.ipynb) — 탁자 클로즈업이
# 제품 놓을 자리를 가장 잘 만든다. 재질(나무 등)은 넣지 않는다 — 업종마다 어울리는
# 재질이 달라 편향이 생긴다.
_BASE = "close-up of an empty tabletop in the foreground, blurred interior behind, soft light"

_SYSTEM = (
    "You turn Korean ad-order details into a short English phrase "
    "for a text-to-image background model — at most 12 words. "
    "Describe only the shop's indoor style and mood, no full scene. "
    "Never mention any food, product, text, or people. Output the phrase only."
)


def build_bg_prompt(industry: str, situation: str = "", tone: str = "") -> str:
    """업종·상황·느낌(한국어)을 영어 배경 프롬프트 한 줄로 변환한다."""
    order = f"업종: {industry} / 상황: {situation} / 느낌: {tone}"
    client = OpenAI()
    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": order}],
    )
    text = (res.choices[0].message.content or "").strip()
    return f"{_BASE}, {text}"
