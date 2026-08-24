from __future__ import annotations

import time

from api import jobs
from app_core import image_backend


def _wait(job: jobs.Job) -> jobs.Job:
    deadline = time.time() + 2
    while job.status in {"queued", "running"} and time.time() < deadline:
        time.sleep(0.01)
    assert job.status == "done"
    return job


def test_재사용되는_작업_스레드가_이전_사용자의_안내를_물려받지_않는다() -> None:
    """API 작업 스레드가 하나여도 각 작업은 빈 실행 문맥에서 시작한다."""
    jobs.clear()

    first = jobs.submit(lambda: image_backend._add_notice("첫 사용자의 안내"))
    _wait(first)

    second = jobs.submit(image_backend.pop_notices)
    assert _wait(second).result == []
