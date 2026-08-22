"""배경 생성 부품 — 실험 근거: notebooks/background_gen_poc.ipynb"""

from functools import cache
from typing import Any

from PIL import Image


@cache
def _load_pipe() -> Any:
    """sd-turbo 파이프라인을 한 번만 만들어 재사용한다 (매번 만들면 수십 초씩 걸린다)."""
    from diffusers import AutoPipelineForText2Image

    from app_core.torch_device import pick

    device, dtype = pick()
    return AutoPipelineForText2Image.from_pretrained("stabilityai/sd-turbo", torch_dtype=dtype).to(
        device
    )


def generate_background(prompt: str, size: tuple[int, int] = (1080, 1080)) -> Image.Image:
    """영어 프롬프트로 광고 배경을 생성한다. (임시 모델 sd-turbo — 추후 SDXL 교체)

    모델이 한국어를 이해하지 못하므로 프롬프트는 영어여야 한다.
    """
    img = _load_pipe()(prompt=prompt, num_inference_steps=2, guidance_scale=0.0).images[0]
    return img.resize(size)
