"""LLM 클라이언트 — MODEL_PROFILE 로 백엔드를 고른다.

    stub    API 키 없이 돌아간다. 테스트·CI 기본값.
    openai  지금 쓰는 실제 백엔드. `llm` extra 필요.
    local   경량·양자화 모델 실험 자리. 아직 비어있다.

이렇게 나눈 이유는 팀이 API 키 하나를 같이 쓰는데, AI 페르소나 쪽이 어떤 LLM을
쓸지 아직 안 정해졌기 때문이다. 백엔드를 여기서 갈아끼우면 부르는 쪽은 안 바뀐다.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Protocol


class ChatClient(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class VisionClient(Protocol):
    """사진을 읽는 쪽. ChatClient 와 나눠 둔 이유는 두 가지다.

    - 텍스트만 쓰는 곳(패널 평가 등)의 가짜 클라이언트가 사진 메서드까지
      구현하지 않아도 되게.
    - 사진은 모델을 따로 고를 여지가 있어서 (텍스트는 mini, 사진은 상위 모델).
    """

    def read_image(self, system: str, image: bytes, mime: str) -> dict: ...


class StubClient:
    """빈 응답만 돌려준다 — API 없이 나머지 배관(병합·되묻기)을 테스트할 때 쓴다."""

    def complete_json(self, system: str, user: str) -> dict:
        return {}

    def read_image(self, system: str, image: bytes, mime: str) -> dict:
        return {}


class OpenAIClient:
    """openai 는 `llm` extra 에만 있다. import 를 생성자 안으로 미뤄서
    이 모듈 자체는 extra 없이도 import 가능하게 한다 (core 는 이 클래스를 안 씀).
    """

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        from openai import OpenAI

        self._client = OpenAI()
        self._model = model

    def complete_json(self, system: str, user: str) -> dict:
        response = self._client.chat.completions.create(
            model=self._model,
            # 같은 입력에 같은 결과가 나와야 한다. 기본값 1.0 이면 사장님이 같은
            # 광고를 두 번 넣었을 때 점수가 달라져 신뢰가 깨진다. 답이 갈리는지
            # 보고 싶을 때만 호출부에서 올린다.
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        return json.loads(content) if content else {}

    def read_image(self, system: str, image: bytes, mime: str) -> dict:
        """사진 한 장을 보여주고 JSON 을 받는다.

        사진은 data URI 로 본문에 실어 보낸다. 파일을 어딘가에 올려두고 URL 을
        주는 방식은 그 URL 이 공개돼야 해서 쓰지 않는다.
        """
        data_uri = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "이 사진을 보고 답해줘."},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                },
            ],
        )
        content = response.choices[0].message.content
        return json.loads(content) if content else {}


def _profile() -> str:
    """호출할 때마다 읽는다 — 테스트에서 MODEL_PROFILE 을 바꿔치기할 수 있게."""
    return os.environ.get("MODEL_PROFILE", "stub")


def get_client() -> ChatClient:
    profile = _profile()
    if profile == "stub":
        return StubClient()
    if profile == "openai":
        return OpenAIClient()
    if profile == "local":
        raise NotImplementedError("local 모델은 아직 붙이지 않았습니다")
    raise ValueError(f"모르는 MODEL_PROFILE 입니다: {profile!r}")


def get_vision_client() -> VisionClient:
    """사진을 읽는 클라이언트.

    local 프로필에서 막지 않고 스텁으로 흘리는 이유: 사진 설명은 없어도 문구가
    만들어진다. 여기서 터뜨리면 사진 한 장 때문에 전체가 멈춘다.
    """
    if _profile() == "openai":
        return OpenAIClient()
    return StubClient()
