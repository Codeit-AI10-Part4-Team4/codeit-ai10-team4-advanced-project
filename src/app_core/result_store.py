"""생성 결과 보관함 ─ 만들어진 광고 이미지를 파일로 남기고 경로를 돌려준다.

DB(ad_images)에는 파일이 아니라 경로만 들어간다. 파일 자체는 여기서 맡는다.
나중에 스토리지(GCS 등)로 옮기더라도 이 부품만 바꾸면 된다.
"""

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

# data/ 는 gitignore 대상이라 생성물이 리포에 올라가지 않는다 (팀 규칙)
# 실행 위치(노트북·앱·도커)에 따라 흔들리지 않도록 리포 루트를 기준으로 잡는다.
_ROOT = Path(__file__).resolve().parents[2]
_RESULTS = _ROOT / "data" / "results"


def save_result(img: Image.Image) -> str:
    """광고 이미지를 저장하고 경로를 돌려준다 (DB ad_images.path 에 넣는 값)"""
    _RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    path = _RESULTS / f"ad_{stamp}.png"
    img.save(path)
    return str(path)


def load_result(path: str) -> Image.Image:
    """저장해둔 광고를 다시 연다. "아까 그게 나왔는데"로 돌아갈 때 쓴다."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"저장된 광고 이미지가 없습니다: {path}")
    return Image.open(p)
