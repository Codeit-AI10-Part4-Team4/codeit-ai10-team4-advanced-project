"""이미지 백엔드 — IMAGE_PROFILE 로 장면 생성기를 고른다 (docs/09 · v1 결정 노트).

llm.py 의 MODEL_PROFILE 과 같은 무늬다: 환경변수를 **호출할 때마다** 읽어
테스트가 바꿔치기할 수 있고, 기본값(local)이면 OpenAI 근처에도 안 가서
키 없는 팀원 환경이 지금까지와 완전히 같이 돈다.

v1 은 프로필이 local | openai 둘이다 — openai 는 실패 시 로컬 폴백 + 화면
안내 (설계의 hybrid 동작을 겸한다). 폴백 없는 strict 모드와 재시도는 후속.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Final

from PIL import Image

from app_core import gen_background

_log = logging.getLogger(__name__)

#: 2026-08-16 벤치마크(eval/run_model_benchmark.py)에서 실측 검증한 모델·품질.
#: Final 이라야 mypy 가 Literal 로 추론한다 — SDK 의 quality 는 Literal 만 받는다.
_MODEL: Final = "gpt-image-2"
_QUALITY: Final = "medium"

_PROFILES: Final = ("local", "openai")

#: 폴백 안내 — pop_notices 가 꺼내며 비운다.
#: ⚠️ 프로세스 전역이라 다중 세션이면 안내가 섞인다. 단일 사용자 시험까지만
#: 허용 — **배포 전에 세션별 전달로 바꿔야 한다** (후속 PR, docs/09 v1 노트).
_notices: list[str] = []


_EDIT_PROMPT = """Turn this customer-taken photo of {product} into a polished, photorealistic
Instagram-ready shop photo. Preserve every visible product exactly as photographed: the same
number, shape, size, colors, layers, condition, arrangement, containers, plates, packages,
labels, and logos. Do not add, remove, replace, repair, restyle, or invent any product,
ingredient, topping, component, claim, or text. You may improve only exposure, white balance,
framing, depth of field, soft natural lighting, and unrelated background clutter. Use a
{tone} mood with useful negative space for later typography. No overlay text, captions, new
logos, people, or watermarks."""


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
    notes = list(_notices)
    _notices.clear()
    return notes


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
        _notices.append("사진 보정에 실패해 원본 사진으로 만들었습니다.")
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
            _notices.append("GPT 이미지 연결이 실패해 로컬 모델로 만들었습니다.")

    return gen_background.generate_background(prompt, size)
