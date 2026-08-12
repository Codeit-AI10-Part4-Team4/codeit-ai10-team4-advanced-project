"""상품 사진 읽기 — 사진을 문구 프롬프트에 넣을 말로 바꾼다."""

from app_core import vision

FULL = {
    "subject": "크로플",
    "looks": ["격자무늬로 바삭하게 구워진 겉면", "위에 올린 생크림"],
    "mood": "따뜻하고 아늑한",
}


class FakeVision:
    def __init__(self, response: object) -> None:
        self.response = response
        self.system: str | None = None
        self.calls = 0

    def read_image(self, system: str, image: bytes, mime: str) -> dict:
        self.system = system
        self.calls += 1
        return self.response  # type: ignore[return-value]  # 망가진 응답도 넣어본다


def test_사진에서_읽은_것을_줄로_만든다() -> None:
    note = vision.describe(b"img", "image/png", client=FakeVision(FULL))
    assert "크로플" in note
    assert "생크림" in note
    assert "따뜻하고 아늑한" in note


def test_빈_항목은_줄을_만들지_않는다() -> None:
    note = vision.describe(b"img", "image/png", client=FakeVision({"mood": "차분한"}))
    assert note == "- 사진의 분위기: 차분한"


def test_아무것도_못_읽으면_빈_문자열() -> None:
    assert vision.describe(b"img", "image/png", client=FakeVision({})) == ""


def test_looks_가_너무_많으면_잘라낸다() -> None:
    many = {"looks": [f"특징{i}" for i in range(10)]}
    note = vision.describe(b"img", "image/png", client=FakeVision(many))
    assert note.count(",") == vision.MAX_LOOKS - 1


def test_형식이_망가져도_안_터진다() -> None:
    """LLM 이 문자열이나 숫자를 섞어 보내도 화면이 죽으면 안 된다."""
    broken = {"subject": {"nested": 1}, "looks": [None, 3, "바삭함"], "mood": ["a"]}
    assert vision.describe(b"img", "image/png", client=FakeVision(broken)) == (
        "- 눈에 띄는 점: 3, 바삭함"
    )


def test_응답이_dict_가_아니면_빈_문자열() -> None:
    assert vision.describe(b"img", "image/png", client=FakeVision("망가짐")) == ""


def test_호출이_실패해도_빈_문자열() -> None:
    """사진 설명은 있으면 좋은 것이다. 없다고 문구를 못 만드는 게 아니다."""

    class Broken:
        def read_image(self, system: str, image: bytes, mime: str) -> dict:
            raise RuntimeError("api down")

    assert vision.describe(b"img", "image/png", client=Broken()) == ""


def test_보이는_것만_적으라고_지시한다() -> None:
    """맛·가격을 지어내면 표시광고법 위반으로 이어진다."""
    client = FakeVision(FULL)
    vision.describe(b"img", "image/png", client=client)
    assert client.system is not None
    assert "실제로 보이는 것만" in client.system
    assert "맛·가격" in client.system
