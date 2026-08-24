"""`python -m api` — 서버를 띄운다.

**uvicorn 으로 직접 띄우면 안 되는 이유.** app.py 와 eval 스크립트는 시작할 때
`config.load_env()` 로 .env 를 읽는데, `uvicorn api.main:app` 은 그 줄을 거치지
않는다. 그러면 서버만 .env 를 못 봐서 KAKAO_REST_KEY 가 비고, 주소→좌표 변환이
죽는다 — 사장님이 직접 등록한 가게는 상권 실측이 통째로 안 나온다.

`api.main` 을 import 하기 **전에** 읽어야 한다. api.session 이 import 시점에
SESSION_SECRET 을 읽기 때문이다.

    python -m api                      # 127.0.0.1:8000
    HOST=0.0.0.0 PORT=8080 python -m api
"""

from __future__ import annotations

import os

from app_core import config

config.load_env()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
