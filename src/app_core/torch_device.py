"""확산 모델을 올릴 장치를 고른다. GPU 가 없으면 CPU 로 내려간다.

배포 서버에 GPU 가 없어서 이미지 생성이 통째로 죽던 것을 막는다. 두 생성기
(`gen_background`·`sketch_gen`)가 각자 `.to("cuda")` 를 박아두고 있었는데,
GPU 없는 환경에서는 파이프라인을 만드는 순간 이렇게 터졌다.

    AssertionError: Torch not compiled with CUDA enabled

`app.py` 의 catch 튜플은 `(OSError, ValueError, RuntimeError, ImportError)` 라
`AssertionError` 를 못 잡는다. 그래서 사장님 화면에 트레이스백이 그대로 떴다.

**float16 도 같이 갈라야 한다.** 반정밀도는 GPU 최적화라 CPU 에서는 느리거나
지원되지 않는 연산이 섞인다. 실측(2026-08-22, CPU float32): sd-turbo 장당
10~13초. 화면 안내가 "20~30초" 라 그 안에 들어온다.

판정을 여기 한 곳에 두는 이유는 두 생성기가 갈라지지 않게 하기 위해서다 —
한쪽만 고치면 스케치 주문에서만 죽는 식으로 절반만 살아난다.
"""

from __future__ import annotations

from typing import Any


def pick() -> tuple[str, Any]:
    """(장치 이름, torch dtype). GPU 가 있으면 cuda+float16, 없으면 cpu+float32.

    torch 는 ml extra 에만 있다. CI·테스트 환경에는 없으므로 호출 시점에
    import 한다 — 두 생성기가 지연 import 를 쓰는 것과 같은 이유다.
    """
    import torch

    if torch.cuda.is_available():
        return "cuda", torch.float16
    return "cpu", torch.float32
