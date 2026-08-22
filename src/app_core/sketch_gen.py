"""스케치 → 광고 이미지 (광고 이미지 만들기 4번).

사장님이 "이런 배치로 만들어주세요" 하고 그림을 올리면, 그 구도를 따라 광고
이미지를 만든다. 실험 근거: notebooks/sketch_controlnet_poc.ipynb

**배경 생성(gen_background)과 다른 점**은 조건이 하나 더 붙는다는 것뿐이다.
같은 sd-turbo 를 쓰므로 팀이 모델을 통일한 상태가 유지된다 — 스케치 때문에
모델을 갈아야 하는 줄 알았는데 실험해보니 아니었다.

실험에서 확정한 값 (아래 상수)
- **스텝 1회.** sd-turbo 는 1~4스텝용으로 만든 모델이라 스텝을 늘리면 오히려
  점묘화처럼 뭉개진다. 8스텝이 가장 나빴다.
- **conditioning 1.0.** 더 올리면 구도는 그대로인데 그림이 망가진다.
- **뒤집지 않는다.** ControlNet scribble 은 보통 검은 배경 + 흰 선을 기대해서
  종이에 그린 그림(흰 배경 + 검은 선)은 뒤집어야 하는 줄 알았는데, 둘 다
  똑같이 동작했다. 손대지 않는 쪽을 고른다.

⚠️ 스케치가 실제로 반영되는지는 **대조로 확인**했다. 빈 그림을 넣으면 그 구조가
   안 나오고, 접시를 왼쪽 아래·오른쪽 위·가로 셋으로 바꾸면 결과도 따라 바뀐다.
   한 장만 보고 "따라간 것 같다" 고 판단하면 안 된다 — 음식 사진에 접시는
   원래 나오기 때문이다.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from PIL import Image

#: 귀한님 gen_background 와 같은 모델. 통일해서 그림체가 갈리지 않게 한다.
MODEL = "stabilityai/sd-turbo"

#: sd-turbo 는 SD 2.1 계열이라 SD1.5용 ControlNet 이 안 맞는다.
CONTROLNET = "thibaud/controlnet-sd21-scribble-diffusers"

#: 실험으로 정한 값. 근거는 위 docstring.
STEPS = 1
CONDITIONING = 1.0

#: sd-turbo 의 학습 해상도. 키우면 구도가 흐트러진다.
SIZE = 512


@cache
def _load_pipe() -> Any:
    """파이프라인을 한 번만 만들어 재사용한다 (매번 만들면 수십 초씩 걸린다)."""
    from diffusers import ControlNetModel, StableDiffusionControlNetPipeline

    from app_core.torch_device import pick

    device, dtype = pick()
    controlnet = ControlNetModel.from_pretrained(CONTROLNET, torch_dtype=dtype)
    return StableDiffusionControlNetPipeline.from_pretrained(
        MODEL,
        controlnet=controlnet,
        torch_dtype=dtype,
        safety_checker=None,
    ).to(device)


def prepare(sketch: Image.Image) -> Image.Image:
    """올라온 스케치를 모델이 받는 형태로 맞춘다.

    크기만 맞추고 색은 건드리지 않는다 — 실험에서 흰 종이·검은 선을 그대로
    넣어도 동작하는 것을 확인했다.
    """
    return sketch.convert("RGB").resize((SIZE, SIZE))


def generate_from_sketch(
    sketch: Image.Image,
    prompt: str,
    conditioning: float = CONDITIONING,
    seed: int | None = None,
) -> Image.Image:
    """스케치 구도를 따라 광고 이미지를 만든다.

    prompt 는 **영어**여야 한다. 모델이 한국어를 이해하지 못한다 —
    한국어 주문을 영어로 바꾸는 것은 prompt_builder 가 맡는다.

    conditioning 을 올리면 스케치를 더 세게 따르지만 그림이 망가진다.
    사장님이 "구도를 더 지켜달라" 고 할 때만 올린다.
    """
    generator = None
    if seed is not None:
        # torch 는 ml extra 에만 있다. CI·테스트에는 없으므로 실제로 필요한
        # 순간까지 import 를 미룬다 — 위 _load_pipe 도 같은 이유로 지연 import.
        import torch

        from app_core.torch_device import pick

        # 제너레이터도 파이프라인과 같은 장치여야 한다. 어긋나면 torch 가
        # "Expected all tensors to be on the same device" 로 막는다.
        device, _ = pick()
        generator = torch.Generator(device).manual_seed(seed)

    return _load_pipe()(
        prompt=prompt,
        image=prepare(sketch),
        num_inference_steps=STEPS,
        # turbo 계열은 guidance 를 쓰지 않는다. 올리면 그림이 타버린다.
        guidance_scale=0.0,
        controlnet_conditioning_scale=conditioning,
        generator=generator,
    ).images[0]
