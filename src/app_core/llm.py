"""LLM 클라이언트 — MODEL_PROFILE 로 백엔드를 고른다.

    stub    API 키 없이 돌아간다. 테스트·CI 기본값.
    openai  지금 쓰는 실제 백엔드. `llm` extra 필요.
    local   경량·양자화 모델 실험 자리. 아직 비어있다.

이렇게 나눈 이유는 팀이 API 키 하나를 같이 쓰는데, AI 페르소나 쪽이 어떤 LLM을
쓸지 아직 안 정해졌기 때문이다. 백엔드를 여기서 갈아끼우면 부르는 쪽은 안 바뀐다.
"""

from __future__ import annotations

import json
import os
from typing import Protocol


class ChatClient(Protocol):
    def complete_json(self, system: str, user: str) -> dict: ...


class StubClient:
    """빈 응답만 돌려준다 — API 없이 나머지 배관(병합·되묻기)을 테스트할 때 쓴다."""

    def complete_json(self, system: str, user: str) -> dict:
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
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        return json.loads(content) if content else {}


def get_client() -> ChatClient:
    """호출할 때마다 환경변수를 읽는다 — 테스트에서 MODEL_PROFILE 을 바꿔치기할 수 있게."""
    profile = os.environ.get("MODEL_PROFILE", "stub")
    if profile == "stub":
        return StubClient()
    if profile == "openai":
        return OpenAIClient()
    if profile == "local":
        raise NotImplementedError("local 모델은 아직 붙이지 않았습니다")
    raise ValueError(f"모르는 MODEL_PROFILE 입니다: {profile!r}")
