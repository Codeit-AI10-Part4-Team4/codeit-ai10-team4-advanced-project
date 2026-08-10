"""사진 보관함 부품 — 업로드된 사진을 저장하고 번호표로 꺼낸다.

주문서(JSON)에 이미지를 실을 수 없어서, 사진은 여기 보관하고
주문서에는 번호만 싣는다 (05_최종계획서 §11의 협의 항목).
"""

from pathlib import Path

from PIL import Image

# data/ 는 gitignore 대상이라 사진이 리포에 올라가지 않는다 (팀 규칙)
_STORE = Path("data/photos")


def save_photo(img: Image.Image) -> int:
    """사진을 보관함에 저장하고 번호표를 돌려준다."""
    _STORE.mkdir(parents=True, exist_ok=True)
    next_id = len(list(_STORE.glob("*.png"))) + 1
    img.save(_STORE / f"{next_id:04d}.png")
    return next_id


def load_photo(photo_id: int) -> Image.Image:
    """번호표로 사진을 꺼낸다. 없으면 에러를 낸다."""
    path = _STORE / f"{photo_id:04d}.png"
    if not path.exists():
        raise FileNotFoundError(f"보관함에 {photo_id}번 사진이 없습니다")
    return Image.open(path)
