"""이미지 백엔드 — IMAGE_PROFILE 로 장면 생성기를 고른다 (docs/09 · v1 결정 노트).

llm.py 의 MODEL_PROFILE 과 같은 무늬다: 환경변수를 **호출할 때마다** 읽어
테스트가 바꿔치기할 수 있고, 기본값(local)이면 OpenAI 근처에도 안 가서
키 없는 팀원 환경이 지금까지와 완전히 같이 돈다.

프로필은 local | openai 둘이다. 사진 없는 openai 생성은 실패 시 로컬 생성으로,
업로드 사진의 고품질 광고 재촬영은 실패 시 좌표 고정 안전 보정으로 폴백한다.
폴백 없는 strict 모드와 재시도는 후속이다.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final, Literal

from PIL import Image

from app_core import gen_background
from app_core.photo_enhance import enhance_uploaded_photo

_log = logging.getLogger(__name__)

#: 2026-08-16 벤치마크(eval/run_model_benchmark.py)에서 실측 검증한 모델·품질.
#: Final 이라야 mypy 가 Literal 로 추론한다 — SDK 의 quality 는 Literal 만 받는다.
_MODEL: Final = "gpt-image-2"
_QUALITY: Final = "medium"
_RESTAGE_QUALITY: Final = "high"

_PROFILES: Final = ("local", "openai")

#: 폴백 안내 — 실행 문맥별로 쌓고 pop_notices 가 꺼내며 비운다.
#: ContextVar 라서 동시에 요청한 사용자끼리 안내가 섞이지 않는다.
_notices: ContextVar[tuple[str, ...]] = ContextVar("image_backend_notices", default=())


_EDIT_PROMPT = """Turn this customer-taken photo of {product} into a polished, photorealistic
Instagram-ready shop photo. Preserve every visible product exactly as photographed: the same
number, shape, size, colors, layers, condition, arrangement, containers, plates, packages,
labels, and logos. Do not add, remove, replace, repair, restyle, or invent any product,
ingredient, topping, component, claim, or text. You may improve only exposure, white balance,
framing, depth of field, soft natural lighting, and unrelated background clutter. Use a
{tone} mood with useful negative space for later typography. No overlay text, captions, new
logos, people, or watermarks."""

RestageStyle = Literal["simple", "poster"]

_RESTAGE_DIRECTION: Final = {
    "simple": """Create a premium, natural Instagram feed photograph with an editorial lifestyle
feel. Make the advertised subject desirable and believable, use warm dimensional light and a
realistic neighborhood-shop setting, and leave a calm area near the upper left for Korean copy
that will be added later. For food or drink, make it naturally appetizing; for other categories,
use category-appropriate commercial styling. The result should feel like a skilled photographer
shot it, not like a glossy 3D render.""",
    "poster": """Create a premium commercial product photograph for an information poster. Use a
clean, controlled set, strong subject focus, balanced centered grouping, realistic depth and
lighting, and enough uncluttered space around the hero subject for a poster layout added later.
For food or drink, make it naturally appetizing; otherwise use category-appropriate styling. The
result should feel like professional advertising photography, not a glossy 3D render.""",
}


@dataclass(frozen=True)
class RestageResult:
    """업로드 사진 재촬영 결과와 실제 AI 연출 성공 여부."""

    image: Image.Image
    staged: bool


class _NamedPng(io.BytesIO):
    """OpenAI multipart 업로드에 파일 이름을 제공하는 메모리 PNG."""

    name = "input.png"


def profile() -> str:
    """지금 쓰는 이미지 백엔드 이름 — local | openai. 모르는 값이면 즉시 죽는다.

    오타(IMAGE_PROFILE=opneai)가 조용히 local 로 흘러가면 "GPT 를 켰는데 왜
    로컬 그림이지"가 된다 — llm.get_client 의 ValueError 와 같은 이유.
    """
    name = os.environ.get("IMAGE_PROFILE", "local")
    if name not in _PROFILES:
        raise ValueError(f"모르는 IMAGE_PROFILE 입니다: {name!r} (local | openai 중 하나)")
    return name


def pop_notices() -> list[str]:
    """쌓인 안내를 꺼내고 비운다. 화면이 재료 준비 직후 한 번 읽는다."""
    notes = list(_notices.get())
    _notices.set(())
    return notes


def _add_notice(message: str, *, unique: bool = False) -> None:
    """현재 사용자 실행 문맥에만 폴백 안내를 남긴다."""
    notices = _notices.get()
    if unique and message in notices:
        return
    _notices.set((*notices, message))


def _openai_scene(prompt: str, size: tuple[int, int]) -> Image.Image:
    """gpt-image-2 로 장면 한 장. 실패는 부르는 쪽이 받아 폴백한다."""
    from openai import OpenAI

    rsp = OpenAI().images.generate(
        model=_MODEL,
        prompt=prompt,
        size="1024x1024",
        quality=_QUALITY,
    )
    if not rsp.data or not rsp.data[0].b64_json:
        raise ValueError("응답에 이미지가 없습니다")

    img = Image.open(io.BytesIO(base64.b64decode(rsp.data[0].b64_json)))
    return img.convert("RGB").resize(size)


def _openai_edit(
    photo: Image.Image,
    product: str,
    tone: str,
    size: tuple[int, int],
) -> Image.Image:
    """gpt-image-2 로 원본 사진 전체를 정돈하되 상품은 그대로 보존한다."""
    from openai import OpenAI

    prepared = photo.convert("RGB")
    prepared.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
    image_file = _NamedPng()
    prepared.save(image_file, format="PNG")
    image_file.seek(0)

    prompt = _EDIT_PROMPT.format(
        product=product,
        tone=tone.strip() or "clean, natural, restrained",
    )
    rsp = OpenAI().images.edit(
        model=_MODEL,
        image=[image_file],
        prompt=prompt,
        size="1024x1024",
        quality=_QUALITY,
    )
    if not rsp.data or not rsp.data[0].b64_json:
        raise ValueError("응답에 이미지가 없습니다")

    img = Image.open(io.BytesIO(base64.b64decode(rsp.data[0].b64_json)))
    return img.convert("RGB").resize(size)


def _restage_prompt(
    *,
    product: str,
    industry: str,
    situation: str,
    tone: str,
    extra: str,
    transcript: str,
    style: RestageStyle,
    reference: str = "",
) -> str:
    """사장님 사진을 참고한 광고 재촬영 지시 — 조판 글자는 모델에 맡기지 않는다.

    `reference` 는 사장님이 "이런 느낌으로" 하고 올린 레퍼런스에서 읽은 분위기
    구절이다(ref_style). 확산 모델 경로와 달리 여기는 CLIP 77토큰 제한이 없어서
    프롬프트 뒤에 붙여도 잘리지 않는다 — **사진 보존(3번)과 레퍼런스 반영(2번)을
    동시에** 할 수 있는 자리다.
    """
    facts = "\n".join(
        line
        for line in (
            f"Shop category: {industry}" if industry.strip() else "",
            f"Product to advertise: {product}" if product.strip() else "",
            f"Promotion or situation: {situation}" if situation.strip() else "",
            f"Requested mood: {tone}" if tone.strip() else "",
            f"Owner's extra request: {extra}" if extra.strip() else "",
            f"Owner's original words: {transcript}" if transcript.strip() else "",
        )
        if line
    )
    # 레퍼런스는 **분위기만** 따른다. 남의 상품이 사장님 광고에 들어가면 안 되므로
    # ref_style 이 애초에 제품·글자를 뺀 구절만 준다 (ref_style.SYSTEM_PROMPT).
    mood = (
        f"\nMatch this visual mood the owner asked for: {reference.strip()}. "
        "Apply it to lighting, color, setting, and styling only — never copy any "
        "product, packaging, or text from that reference."
        if reference.strip()
        else ""
    )
    return f"""Use the uploaded customer photo as the visual reference for a new, high-end
photorealistic advertisement photograph for a Korean neighborhood shop. Freely rebuild the
background, camera framing, lighting, styling, props, and presentation so the result is much
more polished and immediately usable as an ad. Preserve the recognizable core product category
and visual identity from the source, but this is a creative commercial reshoot rather than an
exact restoration.

{_RESTAGE_DIRECTION[style]}

Owner-provided context:
{facts or "No additional owner context."}

Do not render any visible or legible typography anywhere: no overlay text, Korean copy,
letters, numbers, prices, shop names, captions, signs, menus, price tags, labels, watermarks,
or new logos. If the source packaging contains text, preserve the package's overall visual
identity but turn, crop, or soften it so the lettering is unreadable instead of inventing or
changing words.
Do not invent a specific ingredient, certification, discount, award, origin, or factual claim
that the owner did not provide. Avoid plastic-looking surfaces, impossible geometry, excessive
gloss, fake bokeh, duplicated objects, and over-saturated colors.{mood}"""


def _openai_restage(
    photo: Image.Image,
    *,
    product: str,
    industry: str,
    situation: str,
    tone: str,
    extra: str,
    transcript: str,
    style: RestageStyle,
    size: tuple[int, int],
    reference: str = "",
) -> Image.Image:
    """업로드 사진을 참고 이미지로 삼아 광고 촬영본을 새로 만든다."""
    from openai import OpenAI

    prepared = photo.convert("RGB")
    prepared.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
    image_file = _NamedPng()
    prepared.save(image_file, format="PNG")
    image_file.seek(0)

    api_size: Literal["1024x1024", "1536x1024"] = "1024x1024" if style == "simple" else "1536x1024"
    rsp = OpenAI().images.edit(
        model=_MODEL,
        image=[image_file],
        prompt=_restage_prompt(
            product=product,
            industry=industry,
            situation=situation,
            tone=tone,
            extra=extra,
            transcript=transcript,
            style=style,
            reference=reference,
        ),
        size=api_size,
        quality=_RESTAGE_QUALITY,
    )
    if not rsp.data or not rsp.data[0].b64_json:
        raise ValueError("응답에 이미지가 없습니다")

    img = Image.open(io.BytesIO(base64.b64decode(rsp.data[0].b64_json)))
    return img.convert("RGB").resize(size, Image.Resampling.LANCZOS)


def restage_photo(
    photo: Image.Image,
    *,
    product: str,
    industry: str = "",
    situation: str = "",
    tone: str = "",
    extra: str = "",
    transcript: str = "",
    style: RestageStyle = "simple",
    size: tuple[int, int] = (1080, 1080),
    reference: str = "",
) -> RestageResult:
    """사진을 광고 촬영본으로 재연출한다. 실패하면 안전 보정본으로 끝낸다.

    `reference` 를 주면 그 분위기까지 함께 반영한다 — 사장님이 실제 상품 사진과
    레퍼런스를 **둘 다** 올린 경우다 (3번 + 2번).
    """
    try:
        image = _openai_restage(
            photo,
            product=product,
            industry=industry,
            situation=situation,
            tone=tone,
            extra=extra,
            transcript=transcript,
            style=style,
            size=size,
            reference=reference,
        )
        return RestageResult(image=image, staged=True)
    except Exception:  # noqa: BLE001 — 외부 편집 실패가 광고 전체를 막으면 안 된다
        _log.warning("GPT 광고 재촬영 실패 — 안전 보정으로 폴백합니다", exc_info=True)
        message = "AI 광고 촬영에 실패해 원본 사진을 안전 보정해 사용했습니다."
        _add_notice(message, unique=True)

    try:
        fallback = enhance_uploaded_photo(photo)
    except (OSError, ValueError):
        fallback = photo.convert("RGB")
    return RestageResult(image=fallback, staged=False)


def edit_photo(
    photo: Image.Image,
    product: str,
    tone: str = "",
    size: tuple[int, int] = (1080, 1080),
) -> Image.Image:
    """사장님 사진을 보정한다. 실패하면 상품 보호를 위해 원본을 그대로 쓴다.

    이 함수는 openai 프로필의 사진 경로에서만 호출한다. 로컬 프로필은 기존
    누끼·배경 합성을 유지한다. 편집 결과도 사장님 상품을 보존한 사진이므로
    ``staged`` 판단은 부르는 파이프라인이 False 로 유지한다.
    """
    try:
        return _openai_edit(photo, product, tone, size)
    except Exception:  # noqa: BLE001 — 편집 실패가 광고 전체를 막으면 안 된다
        _log.warning("GPT 사진 보정 실패 — 원본을 사용합니다", exc_info=True)
        _add_notice("사진 보정에 실패해 원본 사진으로 만들었습니다.")
        return photo.convert("RGB").resize(size)


def generate_scene(
    prompt: str,
    size: tuple[int, int] = (1080, 1080),
) -> Image.Image:
    """광고 장면 한 장 — openai 프로필이면 GPT, 실패하면 로컬 폴백.

    gen_background.generate_background 와 같은 시그니처라 pipeline 은
    부르는 이름만 바꾸면 된다. 사장님 화면에는 일어난 일만 말하고,
    예외 원문은 로그에만 남긴다 — 외부 오류 문자열은 사용자 문장이 아니다.
    """
    if profile() == "openai":
        try:
            return _openai_scene(prompt, size)
        except Exception:  # noqa: BLE001 — 어떤 실패든 로컬 폴백으로 광고는 만든다
            _log.warning("GPT 이미지 생성 실패 — 로컬로 폴백합니다", exc_info=True)
            _add_notice("GPT 이미지 연결이 실패해 로컬 모델로 만들었습니다.")

    return gen_background.generate_background(prompt, size)
