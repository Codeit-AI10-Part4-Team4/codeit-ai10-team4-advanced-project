from app_core.prompt_builder import build_hero_prompt, build_scene_prompt


class FakeClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.system = ""
        self.user = ""

    def complete_json(self, system: str, user: str) -> dict:
        self.system = system
        self.user = user
        return self.response


def test_촬영기획에_주문정보를_모두_전달한다() -> None:
    client = FakeClient({"prompt": "a bright summer product photo"})

    build_scene_prompt(
        shop="망원상점",
        location="서울 마포구",
        industry="카페",
        product="수박주스",
        situation="여름 신메뉴",
        tone="청량한",
        extra="파란색 분위기",
        transcript="수박주스를 시원하게 보여주세요",
        client=client,
    )

    assert "망원상점" in client.user
    assert "서울 마포구" in client.user
    assert "수박주스" in client.user
    assert "여름 신메뉴" in client.user
    assert "청량한" in client.user
    assert "파란색 분위기" in client.user
    assert "수박주스를 시원하게 보여주세요" in client.user


def test_촬영프롬프트에_사실성_안전장치가_붙는다() -> None:
    client = FakeClient({"prompt": "a refreshing watermelon juice photo"})

    result = build_scene_prompt(
        shop="망원상점",
        location="서울 마포구",
        industry="카페",
        product="수박주스",
        client=client,
    )

    assert "a refreshing watermelon juice photo" in result
    assert "do not invent ingredients" in result
    assert "no text" in result
    assert "no people" in result
    assert "hands, arms" in result


def test_LLM이_비어도_상품이_프롬프트에_남는다() -> None:
    client = FakeClient({})

    result = build_scene_prompt(
        shop="망원상점",
        location="서울 마포구",
        industry="카페",
        product="수박주스",
        client=client,
    )

    assert "수박주스" in result
    assert "professional photorealistic advertising photography" in result
    assert "do not invent ingredients" in result


def test_포스터용_hero는_기존의_짧은_계약을_유지한다() -> None:
    client = FakeClient({"phrase": "fresh watermelon juice"})

    result = build_hero_prompt(
        industry="카페",
        product="수박주스",
        tone="청량한",
        client=client,
    )

    assert "at most 12 words" in client.system
    assert result.startswith("fresh watermelon juice")
    assert "no people" in result
    assert "no hands" in result
    assert "no arms" in result
