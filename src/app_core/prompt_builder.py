"""프롬프트 부품 — 한국어 주문 정보를 배경 생성용 영어 프롬프트로 바꾼다.

배경 생성 모델(sd 계열)이 한국어를 이해하지 못해서 이 번역 단계가 필요하다.
실험 근거: notebooks/background_gen_poc.ipynb (한글 프롬프트 → 엉뚱한 그림)
"""

from openai import OpenAI

# 어떤 주문이 와도 공통으로 지킬 조건 — 제품을 얹을 "빈 무대"여야 한다.
_BASE = "close-up of an empty clean surface in the foreground, blurred interior, soft light"

_SYSTEM = (
    "You turn Korean ad-order details into one short English prompt "
    "for a text-to-image background model. Describe only the empty scene and mood. "
    "Never mention any food, product, text, or people. Output the prompt only."
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
    return f"{text}, {_BASE}"
