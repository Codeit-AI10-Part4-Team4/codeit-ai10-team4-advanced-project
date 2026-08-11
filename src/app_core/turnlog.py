"""턴 로그 — 사장님이 한 말과 그때 뽑힌 값을 한 줄씩 남긴다.

**왜 남기나.** 주문서에는 대화가 끝난 뒤의 최종 값만 남는다. 그래서 "이 발화에서
무엇이 뽑혔나"를 알 수 없고, 골든셋을 만들려면 사람이 상상해서 써야 한다.
실제로 골든셋 43건 중 절반 이상을 그렇게 만들었다.

여기 쌓인 로그를 `eval/export_turns.py` 로 내보내면 **실제 발화로 골든셋을**
채울 수 있다. 정답은 사람이 검수한다 — LLM 이 뽑은 값을 그대로 정답으로 쓰면
자기가 낸 답을 자기가 채점하는 꼴이라 항상 100% 가 나온다.

JSONL 파일에 쓴다. DB 가 아닌 이유는 이게 서비스 데이터가 아니라 개발 자산이고,
스키마가 자주 바뀔 것이며, 그대로 훑어보기 편해야 하기 때문이다.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app_core.schema import AdBriefDraft

DEFAULT_PATH = "data/turns.jsonl"


def log_path() -> Path:
    """호출할 때마다 읽는다 — 테스트에서 바꿔치기할 수 있게."""
    return Path(os.environ.get("ADS_TURNLOG") or DEFAULT_PATH)


def enabled() -> bool:
    """끌 수 있게 해둔다. 배포에서는 개인정보가 섞일 수 있어 기본으로 켜지 않는다."""
    return os.environ.get("ADS_TURNLOG_ENABLED", "1") != "0"


def record(
    utterance: str,
    before: AdBriefDraft,
    after: AdBriefDraft,
    asked: str | None,
    industry: str,
) -> None:
    """한 턴을 기록한다. 실패해도 대화를 멈추지 않는다.

    로그가 안 남는 것보다 대화가 끊기는 게 더 나쁘다.
    """
    if not enabled() or not utterance.strip():
        return

    slots = ("product", "price", "situation", "tone", "extra")
    entry = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "industry": industry,
        # 이 발화 직전 상태. 정정("아니 6000원이요")인지 최초 입력인지 이걸로 갈린다.
        "before": {s: getattr(before, s) for s in slots},
        "utterance": utterance,
        "after": {s: getattr(after, s) for s in slots},
        # 이번 턴에 무엇을 물어보던 중이었는지. 엉뚱한 답이 오는 이유를 여기서 찾는다.
        "asked": asked,
    }

    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 로그는 있으면 좋은 것이지 없으면 안 되는 것이 아니다


def read_all(path: Path | None = None) -> list[dict]:
    """쌓인 턴을 전부 읽는다. 깨진 줄은 건너뛴다."""
    target = path or log_path()
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
