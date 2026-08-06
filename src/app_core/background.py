"""배경 제거 부품 — 실험 근거: notebooks/rembg_poc.ipynb"""

from PIL import Image


def remove_background(img: Image.Image) -> Image.Image:
    """제품 사진의 배경을 제거해 투명 배경(RGBA) 이미지를 반환한다."""
    from rembg import new_session, remove  # type: ignore[import-untyped]

    sess = new_session("isnet-general-use")
    return remove(img, session=sess, post_process_mask=True)
