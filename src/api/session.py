"""로그인한 사람이 누구인지 표시하는 토큰.

`auth.login()` 은 user_id 를 돌려준다. 그걸 그대로 화면에 주고 다시 받으면
**아무나 남의 번호를 적어 보낼 수 있다** — 남의 가게가 통째로 열린다.
그래서 서명을 붙여서 준다. 서명은 서버만 만들 수 있으므로 번호를 바꿔치기하면
검증에서 걸린다.

    토큰 = "{user_id}.{hmac-sha256(secret, user_id)}"

비밀번호 해시와 같은 이유로 표준 라이브러리만 쓴다 (auth.py 참고).

# ponytail: 만료도 없고 폐기(로그아웃)도 없다. 토큰이 새면 비밀을 바꾸는 것 말고는
# 막을 방법이 없다. 지금은 시연이 목적이라 여기까지고, 실제로 열 때는 만료 시각을
# 넣고 서버에 폐기 목록을 두어야 한다.
"""

from __future__ import annotations

import hmac
import os
import secrets
from hashlib import sha256

#: 비밀. 환경변수가 없으면 프로세스마다 새로 만든다 —
#: 서버를 다시 띄우면 로그인이 풀리지만, 코드에 박힌 기본값보다 낫다.
#: 기본값을 두면 그 값이 그대로 배포돼서 누구나 토큰을 위조할 수 있다.
_SECRET = (os.getenv("SESSION_SECRET") or secrets.token_hex(32)).encode()


def _sign(user_id: int) -> str:
    return hmac.new(_SECRET, str(user_id).encode(), sha256).hexdigest()


def issue(user_id: int) -> str:
    """로그인한 사람에게 줄 토큰."""
    return f"{user_id}.{_sign(user_id)}"


def read(token: str | None) -> int | None:
    """토큰에서 user_id 를 꺼낸다. 위조·손상이면 None."""
    if not token or "." not in token:
        return None
    raw, _, sig = token.partition(".")
    if not raw.isdigit():
        return None
    # compare_digest 를 쓰는 이유: == 는 앞에서부터 비교하다 다르면 바로 멈춰서
    # 걸린 시간으로 서명을 한 글자씩 맞춰볼 수 있다.
    if not hmac.compare_digest(sig, _sign(int(raw))):
        return None
    return int(raw)
