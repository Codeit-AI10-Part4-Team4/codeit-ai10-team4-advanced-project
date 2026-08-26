"""프롬프트 부품 — 한국어 주문 정보를 배경 생성용 영어 프롬프트로 바꾼다.

배경 생성 모델(sd 계열)이 한국어를 이해하지 못해서 이 번역 단계가 필요하다.
실험 근거: notebooks/background_gen_poc.ipynb (한글 프롬프트 → 엉뚱한 그림)

모델은 `llm.get_client()` 로 부른다. 직접 `OpenAI()` 를 만들면 `MODEL_PROFILE`
설정이 무시돼서, stub 프로필로 받은 사람이 문구는 조용히 비는데 이미지만
실제 API 를 부르는(= 키가 있으면 돈이 나가는) 상태가 된다.
"""

from app_core.llm import ChatClient, get_client

# 어떤 주문이 와도 공통으로 지킬 조건 — 제품을 놓을 "빈 탁자"가 앞에 있어야 한다.
# 실험 근거: 같은 seed 로 3안 비교(notebooks/background_gen_poc.ipynb) — 탁자 클로즈업이
# 제품 놓을 자리를 가장 잘 만든다. 재질(나무 등)은 넣지 않는다 — 업종마다 어울리는
# 재질이 달라 편향이 생긴다.
_BASE = "close-up of an empty tabletop in the foreground, blurred interior behind, soft light"

_SYSTEM = (
    "You turn Korean ad-order details into a short English phrase "
    "for a text-to-image background model — at most 12 words. "
    "Describe only the shop's indoor style and mood, no full scene. "
    "Never mention any food, product, text, or people. "
    'Output JSON: {"phrase": "..."}'
)

# 사진이 없을 때는 반대로 "주인공 자체"를 그린다. _BASE(빈 무대)와 용도가 반대다.
_HERO_BASE = (
    "professional product photography, centered close-up, soft light, blurred background, "
    "no people, no human body parts, no hands, no arms"
)

_HERO_SYSTEM = (
    "You turn Korean shop-order details into a short English phrase "
    "for a text-to-image model — at most 12 words. "
    "Describe the product itself, appetizing and beautiful. "
    "No text, no people. "
    'Output JSON: {"phrase": "..."}'
)

# 사진 없는 감성형 광고는 제품뿐 아니라 장면 전체를 생성한다.
_SCENE_BASE = (
    "professional photorealistic advertising photography, "
    "hero product centered and dominant, natural depth, "
    "clean composition, negative space for later typography"
)

_SCENE_SAFETY = (
    "preserve factual accuracy; do not invent ingredients, toppings, "
    "components, quantities, quality claims, origin, awards, discounts, "
    "or packaging claims; no text, logos, or watermarks; no people, faces, "
    "human body parts, hands, arms, fingers, human reflections, or human silhouettes"
)

_SCENE_SYSTEM = (
    "You are the photography director for a Korean neighborhood-shop ad. "
    "Turn the supplied Korean order into one concise English image prompt, "
    "at most 80 words. Describe the product presentation, setting, composition, "
    "camera angle, lighting, mood, color palette, textures, and negative space. "
    "Use only facts supplied by the owner. You may creatively choose photographic "
    "treatment, but never invent product details or advertising claims. "
    "Do not render text, shop names, addresses, prices, logos, or people. "
    'Output JSON only: {"prompt": "..."}'
)


def _phrase(system: str, order: str, client: ChatClient | None) -> str:
    """모델이 준 영어 구절. 못 받으면 빈 문자열 — 부르는 쪽이 기본 프롬프트만 쓴다."""
    raw = (client or get_client()).complete_json(system, order)
    return str(raw.get("phrase", "")).strip()


def build_bg_prompt(
    industry: str, situation: str = "", tone: str = "", client: ChatClient | None = None
) -> str:
    """업종·상황·느낌(한국어)을 영어 배경 프롬프트 한 줄로 변환한다.

    구절을 못 받으면 `_BASE` 만 돌려준다. 밋밋한 배경이 나올 뿐 그림은 나오므로
    여기서 터뜨려 이미지 생성 전체를 막을 이유가 없다.
    """
    order = f"업종: {industry} / 상황: {situation} / 느낌: {tone}"
    text = _phrase(_SYSTEM, order, client)
    return f"{_BASE}, {text}" if text else _BASE


def build_hero_prompt(
    industry: str, product: str, tone: str = "", client: ChatClient | None = None
) -> str:
    """사진 없는 주문에서 포스터에 넣을 주인공 이미지용 프롬프트를 만든다."""
    order = f"업종: {industry} / 대상: {product} / 느낌: {tone}"
    text = _phrase(_HERO_SYSTEM, order, client)
    return f"{text}, {_HERO_BASE}" if text else _HERO_BASE


def build_scene_prompt(
    shop: str,
    location: str,
    industry: str,
    product: str,
    situation: str = "",
    tone: str = "",
    extra: str = "",
    transcript: str = "",
    client: ChatClient | None = None,
) -> str:
    """사진 없는 감성형 광고를 위한 촬영 기획 프롬프트를 만든다."""
    order = (
        f"상호: {shop} / 위치: {location} / 업종: {industry} / "
        f"홍보 대상: {product} / 상황: {situation} / 느낌: {tone} / "
        f"그 밖의 요청: {extra}\n"
        f"사장님이 한 말 원문:\n{transcript or '(없음)'}"
    )
    raw = (client or get_client()).complete_json(_SCENE_SYSTEM, order)
    planned = str(raw.get("prompt", "")).strip()
    fallback = f"{_SCENE_BASE}, {product}"
    return f"{planned or fallback}, {_SCENE_SAFETY}"
