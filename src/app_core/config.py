""".env 를 환경변수로 읽어들인다.

도커로 띄우면 compose 가 env_file 로 넣어주지만, 로컬에서 그냥
`streamlit run app.py` 할 때는 아무도 안 넣어준다. 그때를 위한 것이다.

이미 설정된 환경변수는 덮어쓰지 않는다 — compose 가 넣은 값이 이겨야 한다.
"""

from __future__ import annotations

import os
from pathlib import Path

# src/app_core/config.py → parents[2] 가 저장소 루트
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env(path: Path | None = None) -> None:
    """.env 를 읽어 환경변수에 넣는다. 파일이 없으면 아무것도 안 한다."""
    env_path = path or ENV_FILE
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        # 이미 있으면 건드리지 않는다 (compose·CI 가 넣은 값이 우선)
        os.environ.setdefault(key, value)
