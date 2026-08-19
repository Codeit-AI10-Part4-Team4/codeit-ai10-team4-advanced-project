"""스케치 → 광고 이미지.

확산 모델은 GPU 가 있어야 돌아서 테스트에서 대역으로 바꿔치기한다
(AGENTS.md — 무거운 외부 호출은 테스트에서 mock). 여기서 확인하는 것은
**모델이 그린 그림이 아니라 우리가 넘기는 값**이다.
"""

import pytest
from PIL import Image

from app_core import sketch_gen


class FakePipe:
    """호출 인자를 붙잡아 두는 가짜 파이프라인."""

    def __init__(self) -> None:
        self.kwargs: dict = {}

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return type("Result", (), {"images": [Image.new("RGB", (512, 512))]})()


@pytest.fixture
def pipe(monkeypatch: pytest.MonkeyPatch) -> FakePipe:
    fake = FakePipe()
    monkeypatch.setattr(sketch_gen, "_load_pipe", lambda: fake)
    return fake


def sketch(size: tuple[int, int] = (300, 200)) -> Image.Image:
    return Image.new("RGB", size, "white")


# ── 스케치 다듬기 ────────────────────────────────────────────


def test_모델_해상도로_맞춘다() -> None:
    assert sketch_gen.prepare(sketch()).size == (sketch_gen.SIZE, sketch_gen.SIZE)


def test_투명_배경도_받는다() -> None:
    """휴대폰으로 찍거나 앱에서 그린 그림은 RGBA 로 올 수 있다."""
    assert sketch_gen.prepare(Image.new("RGBA", (100, 100))).mode == "RGB"


def test_색을_뒤집지_않는다() -> None:
    """흰 종이·검은 선을 그대로 넣어도 동작하는 것을 실험에서 확인했다.
    뒤집는 코드를 넣으면 그때부터 반대 그림이 들어간다.
    """
    paper = Image.new("RGB", (512, 512), "white")
    assert sketch_gen.prepare(paper).getpixel((10, 10)) == (255, 255, 255)


# ── 생성 ────────────────────────────────────────────────────


def test_스케치와_프롬프트를_넘긴다(pipe: FakePipe) -> None:
    sketch_gen.generate_from_sketch(sketch(), "fried chicken on a plate")
    assert pipe.kwargs["prompt"] == "fried chicken on a plate"
    assert pipe.kwargs["image"].size == (sketch_gen.SIZE, sketch_gen.SIZE)


def test_실험으로_정한_값을_쓴다(pipe: FakePipe) -> None:
    """스텝을 늘리면 점묘화처럼 뭉개진다 — 값이 바뀌면 여기서 걸린다."""
    sketch_gen.generate_from_sketch(sketch(), "prompt")
    assert pipe.kwargs["num_inference_steps"] == 1
    assert pipe.kwargs["controlnet_conditioning_scale"] == 1.0


def test_guidance는_0이다(pipe: FakePipe) -> None:
    """turbo 계열은 guidance 를 쓰지 않는다. 올리면 그림이 타버린다."""
    assert sketch_gen.generate_from_sketch(sketch(), "prompt") is not None
    assert pipe.kwargs["guidance_scale"] == 0.0


def test_구도를_더_세게_따르게_할_수_있다(pipe: FakePipe) -> None:
    sketch_gen.generate_from_sketch(sketch(), "prompt", conditioning=1.5)
    assert pipe.kwargs["controlnet_conditioning_scale"] == 1.5


def test_seed를_안_주면_고정하지_않는다(pipe: FakePipe) -> None:
    """다시 만들기를 누르면 다른 그림이 나와야 한다."""
    sketch_gen.generate_from_sketch(sketch(), "prompt")
    assert pipe.kwargs["generator"] is None


def test_이미지를_돌려준다(pipe: FakePipe) -> None:
    assert sketch_gen.generate_from_sketch(sketch(), "prompt").size == (512, 512)
