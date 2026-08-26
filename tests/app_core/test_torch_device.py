"""GPU 가 없는 배포 환경에서 이미지 생성이 죽지 않는지.

실측(2026-08-22) 배포 서버에 GPU 가 없으면 파이프라인을 만드는 순간
`AssertionError: Torch not compiled with CUDA enabled` 로 터졌고, 그 예외가
`app.py` 의 catch 튜플에 없어 사장님 화면에 트레이스백이 그대로 떴다.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app_core.torch_device import pick


def _fake_torch(monkeypatch: pytest.MonkeyPatch, *, cuda_available: bool) -> ModuleType:
    """무거운 torch 없이 장치 판정에 필요한 최소 표면만 만든다."""
    fake = ModuleType("torch")
    fake.__dict__.update(
        cuda=SimpleNamespace(is_available=lambda: cuda_available),
        float16=object(),
        float32=object(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake)
    return fake


def test_GPU_가_없으면_CPU_와_float32_를_고른다(monkeypatch: pytest.MonkeyPatch) -> None:
    """**float32 도 같이 갈라야 한다.** 반정밀도는 GPU 최적화라 CPU 에서
    느리거나 지원되지 않는 연산이 섞인다."""
    torch = _fake_torch(monkeypatch, cuda_available=False)
    assert pick() == ("cpu", torch.__dict__["float32"])


def test_GPU_가_있으면_cuda_와_float16_을_고른다(monkeypatch: pytest.MonkeyPatch) -> None:
    torch = _fake_torch(monkeypatch, cuda_available=True)
    assert pick() == ("cuda", torch.__dict__["float16"])


def test_두_생성기가_같은_판정을_쓴다() -> None:
    """한쪽만 고치면 스케치 주문에서만 죽는 식으로 절반만 살아난다.

    `.to("cuda")` 나 `torch.float16` 이 다시 박히면 여기서 걸린다.
    """
    from pathlib import Path

    root = Path(__file__).parents[2] / "src" / "app_core"
    for name in ("gen_background.py", "sketch_gen.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert '.to("cuda")' not in source, f"{name} 에 장치가 박혀 있다"
        assert "torch.float16" not in source, f"{name} 에 dtype 이 박혀 있다"
        assert 'torch.Generator("cuda")' not in source, f"{name} 제너레이터에 장치가 박혀 있다"
        assert "torch_device import pick" in source, f"{name} 이 공통 판정을 안 쓴다"
