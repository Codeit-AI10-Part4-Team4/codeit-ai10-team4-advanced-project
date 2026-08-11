"""쌓인 턴 로그를 골든셋 후보 CSV 로 내보낸다.

    python -m eval.export_turns                     # 화면으로 미리보기
    python -m eval.export_turns -o eval/candidates.csv

**LLM 이 뽑은 값을 그대로 정답으로 쓰면 안 된다.** 자기가 낸 답을 자기가 채점하는
꼴이라 항상 100% 가 나온다. 그래서 내보낸 CSV 는 *정답*이 아니라 *후보*다.
사람이 한 줄씩 보면서 틀린 것만 고친 다음, golden_dataset_nlu.csv 에 옮겨 넣는다.

빈칸의 뜻이 골든셋과 같다 — "그 슬롯은 안 뽑혀야 한다".
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from app_core import turnlog

SLOTS = ("product", "price", "situation", "tone")
FIELDS = ["utterance", "product", "price", "situation", "tone", "start", "source", "note"]


def _cell(value: object) -> str:
    """CSV 빈칸 = 안 뽑혀야 함. None 과 "" 를 똑같이 빈칸으로 쓴다."""
    return "" if value in (None, "") else str(value)


def _is_correction(entry: dict) -> bool:
    """직전 상태에 이미 뭔가 차 있었으면 정정일 수 있다.

    빈 주문서에서 시작한 것과 채워진 상태에서 시작한 것은 평가 방식이 다르다.
    """
    return any(v not in (None, "") for v in entry.get("before", {}).values())


def to_rows(entries: list[dict]) -> list[dict[str, str]]:
    """턴 로그 → 골든셋 후보 행. 같은 발화는 한 번만 남긴다."""
    seen: set[str] = set()
    rows = []
    for e in entries:
        said = e.get("utterance", "").strip()
        if not said or said in seen:
            continue
        seen.add(said)
        after = e.get("after", {})
        rows.append(
            {
                "utterance": said,
                **{s: _cell(after.get(s)) for s in SLOTS},
                "start": "filled" if _is_correction(e) else "empty",
                "source": "real",
                # 사람이 검수할 때 참고할 것 — 무엇을 물어보던 중이었는지
                "note": f"검수 필요. 물어보던 항목={e.get('asked')} 업종={e.get('industry')}",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--out", type=Path, help="없으면 화면에 찍는다")
    parser.add_argument("--log", type=Path, help="턴 로그 경로 (기본: ADS_TURNLOG)")
    args = parser.parse_args()

    rows = to_rows(turnlog.read_all(args.log))
    if not rows:
        raise SystemExit("턴 로그가 비어 있습니다. 챗봇으로 몇 번 대화해보세요.")

    target = args.out.open("w", encoding="utf-8", newline="") if args.out else sys.stdout
    try:
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.out:
            target.close()

    if args.out:
        print(f"{len(rows)}건 → {args.out}")
        print("⚠️ 이건 정답이 아니라 후보입니다. 한 줄씩 검수한 뒤 골든셋에 옮기세요.")


if __name__ == "__main__":
    main()
