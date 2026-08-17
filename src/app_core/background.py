"""배경 제거 부품 — 실험 근거: notebooks/rembg_poc.ipynb"""

from functools import cache
from typing import Any

from PIL import Image


@cache
def _session() -> Any:
    """누끼 모델을 한 번만 읽어 재사용한다.

    `isnet-general-use` 는 170MB 급이라 매번 만들면 사장님이 사진을 올릴 때마다
    다시 읽는다. `gen_background._load_pipe` 와 같은 이유·같은 방식이다.
    """
    from rembg import new_session

    return new_session("isnet-general-use")


def remove_background(img: Image.Image) -> Image.Image:
    """제품 사진의 배경을 제거해 투명 배경(RGBA) 이미지를 반환한다."""
    from rembg import remove

    return remove(img, session=_session(), post_process_mask=True)
