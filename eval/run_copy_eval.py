"""골든 브리프로 **문구 품질**을 잰다 — 나온 문구가 규칙을 지키는지.

    MODEL_PROFILE=openai python -m eval.run_copy_eval
    MODEL_PROFILE=openai python -m eval.run_copy_eval -n 1        빠르게 한 번만
    MODEL_PROFILE=openai python -m eval.run_copy_eval --source constructed
    MODEL_PROFILE=openai python -m eval.run_copy_eval --json eval/copy_quality.json

⚠️ **`-m` 으로 부른다.** `python eval/run_copy_eval.py` 로 부르면 sys.path 맨 앞이
저장소 뿌리가 아니라 `eval/` 이 되어 `from eval.copy_metrics ...` 가 깨진다.

실 API 를 호출하므로 pytest 에 넣지 않는다 (AGENTS.md). 프롬프트를 고칠 때마다 손으로 돌린다.

## 왜 필요했나

`tests/app_core/test_copy_gen.py` 의 27건은 전부 **프롬프트에 지시가 들어갔는가**를 본다
(`test_지어내지_말라고_지시한다`·`test_가격이_0이면_넣지_말라고_한다`). 대역이 우리가
시킨 답을 돌려주므로 **모델이 그 지시를 지키는지는 구조적으로 확인할 수 없다.**
NLU 는 99% 까지 올렸지만 그건 "알아듣는지"를 잰 것이고, **정작 결과물인 문구가 좋은지는
한 번도 잰 적이 없다.**

여기는 프롬프트를 안 본다. **나온 문구만** 보고 잰다.

## 점수만 보지 말 것

이 프로젝트에서 고칠 단서는 늘 "틀린 것" 목록에 있었다. 아래 출력의 걸린 문구를
직접 읽어라 — `ungrounded_claims` 는 낱말 계기판이라 오탐이 섞일 수 있고,
그 판단은 사람이 해야 한다.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from app_core import config, copy_gen
from app_core.schema import AdBrief, Store
from eval.copy_metrics import price_violations, ungrounded_claims

# .env 의 OPENAI_API_KEY 를 읽는다. app.py 는 부르는데 eval 스크립트는 안 불러서
# 키가 셸 환경에 없으면 그냥 실패했다. setdefault 라 명령줄에서 준
# MODEL_PROFILE 이 .env 값을 이긴다 — 껐다 켰다 하는 쪽이 명령줄이라 그게 맞다.
config.load_env()

GOLDEN_SET = Path(__file__).parent / "golden_dataset_copy.csv"

#: 주소는 고정 — 문구 생성은 상권을 안 보므로 변수를 늘릴 이유가 없다.
ADDRESS = "서울시 강남구 역삼동"


def load_golden(source: str | None = None, ids: list[str] | None = None) -> list[dict[str, str]]:
    """골든 브리프를 읽는다. `ids` 는 **고친 뒤 그 케이스만 다시 때려보려고** 있다 —
    전체를 다시 도는 것보다 호출당 정보가 훨씬 많다."""
    with GOLDEN_SET.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [
        r
        for r in rows
        if (source is None or r["source"] == source) and (ids is None or r["id"] in ids)
    ]


def build(row: dict[str, str]) -> tuple[AdBrief, Store]:
    """CSV 한 줄 → 주문서·가게."""
    store = Store(
        id=1, user_id=1, industry=row["industry"], name=row["store_name"], address=ADDRESS
    )
    brief = AdBrief(
        goal="copy",
        product=row["product"],
        price=int(row["price"] or 0),
        situation=row["situation"],
        tone=row["tone"],
        extra=row["extra"],
        transcript=[row["transcript"]] if row["transcript"] else [],
        photo_note=row["photo_note"],
    )
    return brief, store


def grounds_of(brief: AdBrief) -> str:
    """모델에게 **사실로 준 것** 전부. 여기 있는 말을 다시 쓴 것은 지어낸 게 아니다."""
    return " ".join(
        [
            brief.product,
            brief.situation,
            brief.tone,
            brief.extra,
            brief.photo_note,
            *brief.transcript,
        ]
    )


def check(brief: AdBrief, candidate: copy_gen.CopyCandidate) -> dict[str, list]:
    """후보 하나를 채점한다. 헤드라인과 서브를 합쳐서 본다 — 광고는 한 덩어리로 읽힌다."""
    text = f"{candidate.headline} {candidate.sub}".strip()
    return {
        "price": price_violations(text, show_price=brief.show_price, price=brief.price),
        "claims": ungrounded_claims(text, grounds_of(brief)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="observed | constructed")
    parser.add_argument(
        "-n",
        "--repeat",
        type=int,
        default=3,
        help="몇 번 반복할지. LLM 은 매번 답이 달라서 한 번으로는 판단할 수 없다 (기본 3)",
    )
    parser.add_argument("--json", type=Path, help="측정 결과를 저장할 경로")
    parser.add_argument(
        "--id",
        nargs="+",
        help="이 id 들만 돌린다. 고친 뒤 전에 걸린 케이스를 집중해서 다시 볼 때",
    )
    args = parser.parse_args()

    rows = load_golden(args.source, args.id)
    if not rows:
        raise SystemExit(f"해당하는 케이스가 없습니다: {args.source or ''} {args.id or ''}".strip())

    total = wanted = 0
    price_bad: list[dict] = []
    claim_bad: list[dict] = []
    claim_kinds: Counter[str] = Counter()

    for run in range(args.repeat):
        for row in rows:
            brief, store = build(row)
            wanted += copy_gen.CANDIDATE_COUNT
            for candidate in copy_gen.generate(brief, store):
                total += 1
                found = check(brief, candidate)
                text = f"{candidate.headline} / {candidate.sub}".strip(" /")
                if found["price"]:
                    price_bad.append(
                        {"id": row["id"], "run": run, "text": text, "why": found["price"]}
                    )
                if found["claims"]:
                    claim_bad.append(
                        {
                            "id": row["id"],
                            "run": run,
                            "text": text,
                            "why": [f"{kind}:{term}" for kind, term in found["claims"]],
                        }
                    )
                    for kind, _ in found["claims"]:
                        claim_kinds[kind] += 1

    # ── 보고 ────────────────────────────────────────────────
    print(
        f"브리프 {len(rows)}건 × {args.repeat}회"
        + (f" (source={args.source})" if args.source else "")
    )
    print(f"후보 {total}건 생성 (요청 {wanted}건 — 길이·형식 위반은 버려진다)")
    print()
    print(f"  {'가격 규칙 위반':16s} {len(price_bad):3d}건" + _rate(len(price_bad), total))
    print(f"  {'근거 없는 주장':16s} {len(claim_bad):3d}건" + _rate(len(claim_bad), total))
    if claim_kinds:
        print("      " + " · ".join(f"{k} {v}" for k, v in claim_kinds.most_common()))

    _show("가격 규칙 위반", price_bad)
    _show("근거 없는 주장 (계기판 — 오탐일 수 있으니 직접 읽을 것)", claim_bad)

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "briefs": len(rows),
                    "repeat": args.repeat,
                    "candidates": total,
                    "requested": wanted,
                    "price_violations": price_bad,
                    "ungrounded_claims": claim_bad,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n저장: {args.json}")


def _rate(count: int, total: int) -> str:
    return f"  ({count / total:.0%})" if total else ""


def _show(title: str, items: list[dict]) -> None:
    if not items:
        print(f"\n{'─' * 60}\n{title} — 없음")
        return
    print(f"\n{'─' * 60}\n{title} {len(items)}건\n")
    for item in items:
        print(f'  [{item["id"]}] "{item["text"]}"')
        for why in item["why"]:
            print(f"      {why}")
        print()


if __name__ == "__main__":
    main()
