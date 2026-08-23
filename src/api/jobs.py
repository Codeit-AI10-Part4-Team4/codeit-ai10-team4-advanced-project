"""오래 걸리는 작업을 등록하고 상태를 물어보는 통로.

**왜 필요한가.** 광고 이미지 한 장이 GPU 없는 기계에서 18초 걸린다(실측,
1080x1080, 3회 중앙값). 그냥 응답을 붙들고 있으면 브라우저는 멈춘 것처럼 보이고,
프록시·게이트웨이는 대개 30~60초에서 끊는다. 그래서 **등록하고 물어보는** 모양으로
바꾼다 — 202 로 번호를 받고, 그 번호로 상태를 물어본다.

    POST /ads/image   -> 202 {"job_id": "..."}
    GET  /jobs/{id}   -> {"status": "running"} ... {"status": "done"}

# ponytail: 프로세스 메모리 + 스레드풀이다. 서버를 재시작하면 진행 중이던 작업이
# 날아가고, 여러 대로 띄우면 등록한 곳과 물어보는 곳이 갈릴 수 있다. 지금 목적은
# 시연 한 판이라 여기까지다 — 여러 대로 띄우게 되면 Redis 나 DB 로 옮긴다.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Literal

Status = Literal["running", "done", "failed"]

#: 동시에 돌릴 작업 수. 이미지 생성이 CPU 를 다 쓰므로 늘려도 각자 느려질 뿐이다.
MAX_WORKERS = 2

#: 끝난 작업을 얼마나 들고 있을지(초). 화면이 결과를 가져갈 시간은 줘야 하고,
#: 무한정 들고 있으면 이미지가 메모리에 쌓인다.
KEEP_DONE_SEC = 30 * 60


@dataclass
class Job:
    id: str
    status: Status = "running"
    result: Any = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None

    @property
    def elapsed_ms(self) -> int:
        return int(((self.ended_at or time.time()) - self.started_at) * 1000)


_jobs: dict[str, Job] = {}
_lock = Lock()
_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="job")


def submit(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Job:
    """작업을 등록하고 바로 돌려준다. 결과는 `get()` 으로 물어본다."""
    _sweep()
    job = Job(id=uuid.uuid4().hex)
    with _lock:
        _jobs[job.id] = job

    def run() -> None:
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - 무엇이 터지든 작업만 실패시킨다
            # 여기서 삼키지 않으면 스레드가 조용히 죽고 화면은 영원히 running 을 본다.
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "failed"
        else:
            job.result = result
            job.status = "done"
        finally:
            job.ended_at = time.time()

    _pool.submit(run)
    return job


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def _sweep(now: float | None = None) -> None:
    """끝난 지 오래된 작업을 버린다. 등록할 때마다 한 번씩 훑는다."""
    now = time.time() if now is None else now
    with _lock:
        stale = [
            k
            for k, j in _jobs.items()
            if j.ended_at is not None and now - j.ended_at > KEEP_DONE_SEC
        ]
        for k in stale:
            del _jobs[k]


def clear() -> None:
    """테스트에서 작업 목록을 비운다."""
    with _lock:
        _jobs.clear()
