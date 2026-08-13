"""골든셋으로 NLU 추출 정확도를 잰다.

    MODEL_PROFILE=openai python eval/run_nlu_eval.py
    MODEL_PROFILE=openai python eval/run_nlu_eval.py --source real   출처별로 나눠 보기

실 API 를 호출하므로 pytest 에는 넣지 않는다 (AGENTS.md — 외부 API 호출은
비용·비결정성 때문에 테스트에서 mock). 프롬프트를 고칠 때마다 손으로 돌린다.

**한 번 재고 끝낼 것이 아니라, 고치기 전후를 비교하는 데 쓴다.**
점수만 보지 말고 아래 "틀린 것" 목록을 봐야 무엇을 고칠지 알 수 있다.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app_core import chat
from app_core.schema import AdBriefDraft, Store
from eval.metrics import SLOTS, failures, overall_accuracy, slot_accuracy

GOLDEN_SET = Path(__file__).parent / "golden_dataset_nlu.csv"

#: 발화만 평가한다. 가게는 고정 — 업종이 바뀌면 변수가 하나 더 늘어난다.
STORE = Store(id=1, user_id=1, industry="chicken", name="교촌치킨", address="서울시 강남구 역삼동")


def load_golden(source: str | None = None) -> list[dict[str, str]]:
    with GOLDEN_SET.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if source is None or r["source"] == source]


def expected_of(row: dict[str, str]) -> dict:
    """CSV 빈칸의 뜻: 그 슬롯은 **안 뽑혀야** 한다."""
    return {
        "product": row["product"] or None,
        "price": int(row["price"]) if row["price"] else None,
        "situation": row["situation"],
        "tone": row["tone"],
    }


#: 이미 채워진 상태에서만 나오는 발화가 있다 — "아니 6000원이요" 같은 정정.
#: 빈 주문서에 넣으면 정정인지 최초 입력인지 구분이 안 돼 평가가 성립하지 않는다.
FILLED_START = AdBriefDraft(
    goal="copy",
    product="크로플",
    price=4500,
    situation="신메뉴",
    tone="따뜻한",
    asked=["situation", "tone"],
)


def start_draft(row: dict[str, str]) -> AdBriefDraft:
    """이 케이스를 어떤 상태에서 시작할지. CSV 의 start 컬럼이 정한다."""
    if row.get("start") == "filled":
        return FILLED_START
    return AdBriefDraft(goal="copy")


def predict(row: dict[str, str]) -> dict:
    """발화 하나를 넣었을 때 나오는 주문서 상태.

    한 턴만 본다 — 여러 턴을 이으면 무엇 때문에 틀렸는지 알 수 없다.
    """
    draft = chat.respond(start_draft(row), row["utterance"], STORE).draft
    return {slot: getattr(draft, slot) for slot in SLOTS}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", help="real | observed | constructed")
    parser.add_argument(
        "-n",
        "--repeat",
        type=int,
        default=3,
        help="몇 번 반복할지. LLM 은 매번 답이 달라서 한 번으로는 판단할 수 없다 (기본 3)",
    )
    args = parser.parse_args()

    rows = load_golden(args.source)
    if not rows:
        raise SystemExit(f"해당하는 케이스가 없습니다: {args.source}")

    expectations = [expected_of(r) for r in rows]

    #: 케이스별로 몇 번 실패했는지. 매번 실패하는 것과 가끔 실패하는 것은 성격이 다르다.
    fail_count = dict.fromkeys(range(len(rows)), 0)
    fail_detail: dict[int, dict] = {}
    overalls, slot_runs = [], []

    for _ in range(args.repeat):
        predictions = [predict(r) for r in rows]
        overalls.append(overall_accuracy(predictions, expectations))
        slot_runs.append(slot_accuracy(predictions, expectations))
        for i, slots in failures(predictions, expectations):
            fail_count[i] += 1
            fail_detail[i] = slots

    print(
        f"{len(rows)}개 발화 × {args.repeat}회"
        + (f" (source={args.source})" if args.source else "")
    )
    print()
    for slot in slot_runs[0]:
        scores = [run[slot] for run in slot_runs]
        spread = f"  ({min(scores):.0%}~{max(scores):.0%})" if min(scores) != max(scores) else ""
        print(f"  {slot:10s} {sum(scores) / len(scores):5.0%}{spread}")
    spread = (
        f"  ({min(overalls):.0%}~{max(overalls):.0%})" if min(overalls) != max(overalls) else ""
    )
    print(f"\n  {'전체 일치':10s} {sum(overalls) / len(overalls):5.0%}{spread}")

    wrong = {i: n for i, n in fail_count.items() if n}
    if not wrong:
        print("\n틀린 것 없음")
        return

    print(f"\n{'─' * 60}\n틀린 것 {len(wrong)}건  (n/{args.repeat} = 몇 번 틀렸는지)\n")
    # 매번 틀리는 것부터. 이게 진짜 결함이고, 가끔 틀리는 것은 흔들림이다.
    for i, n in sorted(wrong.items(), key=lambda kv: -kv[1]):
        mark = "❌ 매번" if n == args.repeat else f"⚠️ {n}/{args.repeat}"
        print(f'  {mark}  "{rows[i]["utterance"]}"   [{rows[i]["source"]}]')
        for slot, (got, want) in fail_detail[i].items():
            print(f"      {slot:10s} 뽑음={got!r}  정답={want!r}")
        print()


if __name__ == "__main__":
    main()
