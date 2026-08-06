"""가게 정보 등록·조회.

로그인이 없다. 세션 쿠키(UUID)를 열쇠로 프로필을 저장하고 불러온다.

저장소는 인터페이스로 분리한다. 지금은 JSON 파일이고, 나중에 DuckDB 로 바꿀 때
ProfileStore 구현만 갈아끼우면 호출부는 바뀌지 않는다.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from app_core.schema import StoreProfile

DEFAULT_DATA_DIR = "data"


def data_dir() -> Path:
    """저장 위치. 배포·테스트에서 ADS_DATA_DIR 로 옮긴다.

    호출할 때마다 읽는다 — import 시점에 고정하면 테스트에서 바꿔치기가 안 된다.
    """
    return Path(os.environ.get("ADS_DATA_DIR") or DEFAULT_DATA_DIR)


class ProfileStore(Protocol):
    """가게 정보 저장소."""

    def load(self, session_id: str) -> StoreProfile | None: ...

    def save(self, session_id: str, profile: StoreProfile) -> None: ...


class JsonProfileStore:
    """JSON 파일 저장소 — 1단계.

    세션마다 파일 하나. data/ 는 gitignore 되어 있다.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or data_dir()) / "profiles"

    def _path(self, session_id: str) -> Path:
        # 세션 id 가 경로에 그대로 들어가면 ../ 같은 값으로 다른 곳을 덮어쓸 수 있다.
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError("쓸 수 없는 session_id 입니다")
        return self.root / f"{safe}.json"

    def load(self, session_id: str) -> StoreProfile | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return StoreProfile.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, session_id: str, profile: StoreProfile) -> None:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 쓰다가 죽으면 파일이 반쯤 남는다. 임시 파일에 쓰고 한 번에 바꾼다.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as f:
            f.write(profile.model_dump_json(indent=2))
            tmp = Path(f.name)
        tmp.replace(path)


def register(
    session_id: str,
    industry: str,
    address: str,
    name: str | None = None,
    phone: str | None = None,
    store: ProfileStore | None = None,
) -> StoreProfile:
    """가게 정보를 등록한다. 값이 틀리면 여기서 걸린다.

    Raises:
        pydantic.ValidationError: 모르는 업종이거나 서울 밖 주소일 때
    """
    profile = StoreProfile(industry=industry, address=address, name=name, phone=phone)
    (store or JsonProfileStore()).save(session_id, profile)
    return profile


def get(session_id: str, store: ProfileStore | None = None) -> StoreProfile | None:
    """등록된 가게 정보를 불러온다. 없으면 None."""
    return (store or JsonProfileStore()).load(session_id)


def as_dict(profile: StoreProfile) -> dict:
    """다른 담당에게 넘길 형태."""
    return json.loads(profile.model_dump_json())
