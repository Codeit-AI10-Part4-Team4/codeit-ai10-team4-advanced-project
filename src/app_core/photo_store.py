"""사진 보관함 — 사장님이 올린 상품 사진.

사진은 DB 에도 주문서 JSON 에도 넣지 않는다. 파일로 따로 두고 **번호만**
주고받는다 (`AdBrief.photo_id`). 이미지 담당·문구 담당이 같은 번호로 같은
파일을 찾는다.

⚠️ 지금은 로컬 폴더다. 개발 중엔 compose 가 프로젝트 폴더를 통째로 마운트해서
   (`.:/app`) 컨테이너를 지워도 사진은 호스트에 남는다. 운영에서는 GCS 등으로
   바꾼다 — 그때 바뀌는 건 이 파일뿐이고 부르는 쪽은 그대로다.

⚠️ 소유자 검사가 없다. 번호만 알면 남의 사진을 읽을 수 있다. 지금은 화면이
   세션에 든 번호만 넘기므로 그럴 경로가 없지만, API 로 열 때는 반드시 붙여야 한다.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DIR = "data/photos"

#: 받는 형식. 확장자를 그대로 남겨야 나중에 mime 을 알 수 있다.
MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

#: 휴대폰 사진 한 장 기준. 이보다 크면 비전 호출이 느리고 비싸진다.
MAX_BYTES = 8 * 1024 * 1024


def photo_dir() -> Path:
    """보관함 위치. 호출할 때마다 읽는다 — 테스트에서 tmp_path 로 바꿔치기하려고."""
    return Path(os.environ.get("ADS_PHOTO_DIR") or DEFAULT_DIR)


def _next_id(folder: Path) -> int:
    """가장 큰 번호 + 1.

    파일 개수로 세면 안 된다 — 중간 하나를 지우는 순간 이미 쓴 번호가 다시
    나와서 남의 사진을 덮어쓴다.
    """
    used = [int(p.stem) for p in folder.iterdir() if p.stem.isdigit()]
    return max(used, default=0) + 1


def save(data: bytes, filename: str) -> int:
    """사진을 보관하고 번호를 돌려준다."""
    suffix = Path(filename).suffix.lower()
    if suffix not in MIME:
        raise ValueError(f"지원하지 않는 형식입니다: {suffix or filename!r}")
    if not data:
        raise ValueError("빈 파일입니다")
    if len(data) > MAX_BYTES:
        raise ValueError(f"사진이 너무 큽니다 (최대 {MAX_BYTES // 1024 // 1024}MB)")

    folder = photo_dir()
    folder.mkdir(parents=True, exist_ok=True)
    photo_id = _next_id(folder)
    (folder / f"{photo_id:04d}{suffix}").write_bytes(data)
    return photo_id


def path_of(photo_id: int) -> Path | None:
    """번호로 파일을 찾는다. 확장자를 모르므로 훑는다."""
    folder = photo_dir()
    if not folder.is_dir():
        return None
    for suffix in MIME:
        candidate = folder / f"{photo_id:04d}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def load(photo_id: int) -> tuple[bytes, str] | None:
    """(사진 내용, mime). 없으면 None."""
    found = path_of(photo_id)
    if found is None:
        return None
    return found.read_bytes(), MIME[found.suffix.lower()]
