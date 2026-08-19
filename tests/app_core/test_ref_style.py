"""레퍼런스 이미지 → 분위기 구절."""

from app_core import ref_style


class FakeVision:
    def __init__(self, response: object) -> None:
        self.response = response
        self.system: str | None = None

    def read_image(self, system: str, image: bytes, mime: str) -> dict:
        self.system = system
        return self.response  # type: ignore[return-value]  # 망가진 응답도 넣어본다


def read(response: object) -> str:
    return ref_style.describe_style(b"img", "image/png", client=FakeVision(response))


# ── 뽑기 ────────────────────────────────────────────────────


def test_분위기_구절을_돌려준다() -> None:
    assert read({"phrase": "warm golden light, rustic wooden surface"}) == (
        "warm golden light, rustic wooden surface"
    )


def test_키_이름이_달라도_건진다() -> None:
    """프롬프트에 키를 못 박지 않았으므로 모델이 아무 이름이나 쓸 수 있다."""
    assert read({"style": "dim candlelight, deep shadows"}) == "dim candlelight, deep shadows"


def test_따옴표와_마침표를_벗겨낸다() -> None:
    assert read({"phrase": '  "soft morning light."  '}) == "soft morning light"


def test_너무_길면_잘라낸다() -> None:
    """CLIP 이 77토큰에서 자른다. 길면 앞의 조건이 밀려난다."""
    long = " ".join(f"word{i}" for i in range(40))
    assert len(read({"phrase": long}).split()) == ref_style.MAX_WORDS


def test_빈_응답이면_빈_문자열() -> None:
    assert read({}) == ""


def test_빈_문자열만_오면_빈_문자열() -> None:
    """읽을 수 없으면 빈 문자열을 내라고 지시해뒀다."""
    assert read({"phrase": "  "}) == ""


def test_형식이_망가져도_안_터진다() -> None:
    assert read("망가짐") == ""
    assert read({"phrase": {"nested": 1}}) == ""


def test_호출이_실패해도_빈_문자열() -> None:
    """레퍼런스는 있으면 좋은 것이지 없다고 광고를 못 만드는 게 아니다."""

    class Broken:
        def read_image(self, system: str, image: bytes, mime: str) -> dict:
            raise RuntimeError("api down")

    assert ref_style.describe_style(b"img", "image/png", client=Broken()) == ""


def test_상품을_말하지_말라고_지시한다() -> None:
    """이게 무너지면 남의 광고에 있던 상품이 사장님 광고로 들어온다.
    img2img 를 버린 이유가 정확히 그것이었다.
    """
    client = FakeVision({"phrase": "warm light"})
    ref_style.describe_style(b"img", "image/png", client=client)
    assert client.system is not None
    assert "Never mention the product" in client.system


# ── 프롬프트에 얹기 ──────────────────────────────────────────


def test_분위기를_뒤에_붙인다() -> None:
    """잘릴 때 상품·구도가 먼저 살아남아야 한다."""
    assert ref_style.apply_to("fried chicken", "warm light") == "fried chicken, warm light"


def test_분위기가_없으면_그대로_둔다() -> None:
    assert ref_style.apply_to("fried chicken", "") == "fried chicken"
