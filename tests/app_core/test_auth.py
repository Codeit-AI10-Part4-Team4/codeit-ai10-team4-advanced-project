"""로그인."""

import pytest

from app_core import auth


def test_가입하고_로그인한다() -> None:
    user_id = auth.signup("사장님", "password123")
    assert auth.login("사장님", "password123") == user_id


def test_비밀번호가_틀리면_None() -> None:
    auth.signup("사장님", "password123")
    assert auth.login("사장님", "wrongpassword") is None


def test_없는_아이디도_None() -> None:
    """어떤 아이디가 존재하는지 알려주지 않으려고 실패를 구분하지 않는다."""
    assert auth.login("없는사람", "password123") is None


def test_같은_아이디로_두_번_가입할_수_없다() -> None:
    auth.signup("사장님", "password123")
    with pytest.raises(ValueError, match="이미 있는"):
        auth.signup("사장님", "otherpassword")


def test_짧은_비밀번호는_거부한다() -> None:
    with pytest.raises(ValueError, match="8자"):
        auth.signup("사장님", "short")


def test_빈_아이디는_거부한다() -> None:
    with pytest.raises(ValueError, match="아이디"):
        auth.signup("   ", "password123")


def test_비밀번호를_평문으로_저장하지_않는다() -> None:
    stored = auth.hash_password("password123")
    assert "password123" not in stored


def test_같은_비밀번호도_해시가_다르다() -> None:
    """소금이 매번 달라야 한 명이 뚫려도 나머지가 안전하다."""
    assert auth.hash_password("password123") != auth.hash_password("password123")


def test_망가진_해시는_통과시키지_않는다() -> None:
    assert auth.verify("password123", "쓰레기값") is False
