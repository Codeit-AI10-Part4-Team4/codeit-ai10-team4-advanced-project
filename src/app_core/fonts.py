"""글꼴 부품 — 역할(제목·본문·손글씨)로 글꼴을 찾아준다.

리포에 동봉한 글꼴(assets/fonts)을 먼저 쓰고, 없으면 OS 기본 한글 글꼴로 물러선다.
OS 글꼴에만 기대면 도커·CI(리눅스)에서 한글이 깨지기 때문이다.
동봉 글꼴은 전부 OFL(상업 이용 가능)이며 라이선스 원문을 같은 폴더에 둔다.
"""

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# 역할별 후보 — 앞에 있는 것부터 찾는다.
_ROLES = {
    "display": ["BlackHanSans-Regular.ttf", "NotoSansKR-Bold.ttf"],
    "body": ["NotoSansKR-Bold.ttf"],
    "body_light": ["NotoSansKR-Regular.ttf"],
    "script": ["NanumPenScript-Regular.ttf", "NotoSansKR-Regular.ttf"],
}

_OS_FALLBACK = [
    "C:/Windows/Fonts/malgunbd.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]


@lru_cache(maxsize=256)
def load(role: str, size: int) -> ImageFont.FreeTypeFont:
    """역할 이름으로 글꼴을 연다. 같은 요청은 캐시해서 다시 읽지 않는다."""
    for name in _ROLES.get(role, []):
        path = _ASSETS / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    for path_str in _OS_FALLBACK:
        try:
            return ImageFont.truetype(path_str, size)
        except OSError:
            continue
    raise OSError("한글 글꼴을 찾지 못했습니다 (assets/fonts 또는 OS 글꼴 확인)")


def fit(text: str, max_width: int, start: int, role: str = "body", floor: int = 20):
    """글자가 폭을 넘치면 크기를 줄여 한 줄에 들어가게 한다."""
    size = start
    while size > floor:
        font = load(role, size)
        if font.getlength(text) <= max_width:
            return font
        size -= 4
    return load(role, floor)
