"""로그인.

비밀번호는 표준 라이브러리 scrypt 로 해시한다 — 외부 의존을 늘리지 않으면서
느린 해시를 쓰기 위해서다. 평문은 어디에도 저장하지 않는다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy import select

from app_core import db

_SALT_BYTES = 16
# scrypt 파라미터. 값을 바꾸면 기존 해시를 못 푼다 — 바꿔야 하면 재해시가 필요하다.
_N, _R, _P = 2**14, 8, 1


def _hash(password: str, salt: bytes) -> str:
    key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"{salt.hex()}${key.hex()}"


def hash_password(password: str) -> str:
    return _hash(password, secrets.token_bytes(_SALT_BYTES))


def verify(password: str, stored: str) -> bool:
    try:
        salt_hex, _ = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    # 타이밍 공격을 막으려고 == 대신 상수 시간 비교를 쓴다.
    return hmac.compare_digest(_hash(password, salt), stored)


def signup(username: str, password: str) -> int:
    """가입하고 사용자 id 를 돌려준다.

    Raises:
        ValueError: 아이디가 비었거나 비밀번호가 짧거나 이미 있는 아이디일 때
    """
    username = username.strip()
    if not username:
        raise ValueError("아이디를 입력해주세요")
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다")

    with db.session() as s:
        if s.scalar(select(db.User).where(db.User.username == username)):
            raise ValueError("이미 있는 아이디입니다")
        user = db.User(username=username, password_hash=hash_password(password))
        s.add(user)
        s.flush()
        return user.id


def login(username: str, password: str) -> int | None:
    """맞으면 사용자 id, 틀리면 None.

    아이디가 없을 때와 비밀번호가 틀릴 때를 구분해서 알려주지 않는다 —
    어떤 아이디가 존재하는지 알려주는 셈이 되기 때문이다.
    """
    with db.session() as s:
        user = s.scalar(select(db.User).where(db.User.username == username.strip()))
        if user and verify(password, user.password_hash):
            return user.id
    return None
