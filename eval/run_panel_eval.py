"""실제 LLM 으로 패널 평가를 한 번 돌려보고 **탈락률**을 잰다.

여기까지는 전부 `FakeClient` 로만 검증했다. 모델이 `evidence` 규칙을 실제로
지키는지는 돌려봐야 안다. 이 숫자가 나빠지면 화면(F6)이 아니라 프롬프트를
먼저 고쳐야 하므로, F6 착수 전에 재는 것이 목적이다.

    MODEL_PROFILE=openai python eval/run_panel_eval.py
    MODEL_PROFILE=openai python eval/run_panel_eval.py --runs 3   # 재현성용

`--runs N` 은 같은 입력을 N 번 돌려 점수가 얼마나 흔들리는지 본다.
`SIGMA_MAX` 는 지금 임의값(20)이라 이 측정으로 실측 근거를 만든다.

DuckDB 를 안 쓴다 — 골든 픽스처를 그대로 읽으므로 ETL 없이도 돌아간다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app_core.config import load_env
from app_core.panel.aggregate import AggregationError
from app_core.panel.evaluator import MAX_EVAL_CALLS, evaluate
from app_core.panel.schemas import EvaluationResult, Panel
from app_core.schema import AdBrief, CopyCandidate, Store, StoreInput

FIXTURE = ROOT / "tests" / "fixtures" / "features_yeoksam_20261.json"

#: 역삼역 커피-음료 상권에 맞춘 샘플. 가격은 이 상권 객단가(9,546원) 근처로 잡아
#: 가격 저항이 나오는지 보려는 것이다.
SAMPLE_HEADLINE = "점심 10분 컷, 크로플"
SAMPLE_SUB = "주문하고 자리 잡으면 나옵니다"
SAMPLE_COPY = CopyCandidate(headline=SAMPLE_HEADLINE, sub=SAMPLE_SUB)


class FailureCounter(logging.Handler):
    """evaluator 가 DEBUG 로 남기는 탈락 사유를 센다.

    `EvaluationResult` 는 탈락 **수**만 주고 이유는 안 준다. 프롬프트를 고칠지
    판단하려면 스키마가 깨진 건지 수치를 지어낸 건지가 갈려야 한다.
    """

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.schema = 0
        self.evidence = 0
        self.samples: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        if text.startswith("스키마 실패"):
            self.schema += 1
        elif text.startswith("근거 대조 실패"):
            self.evidence += 1
        if len(self.samples) < 5:
            self.samples.append(text)


def load_panel() -> Panel:
    with FIXTURE.open(encoding="utf-8") as fp:
        return Panel.model_validate(json.load(fp))


def sample_store() -> Store:
    base = StoreInput(industry="cafe", name="역삼 크로플", address="서울시 강남구 역삼동 823")
    return Store(**base.model_dump(), id=1, user_id=1)


def sample_brief(price: int = 9500, product: str = "크로플") -> AdBrief:
    """평가에 쓸 주문서.

    `price=0` 은 "가격 없음"이다(`AdBrief.show_price`). 걸림돌이 입력에
    반응하는지 재는 **결정적 시험**이라 옵션으로 뺐다 — 적히지도 않은 가격을
    걸림돌로 고르면 그건 광고를 본 게 아니다 (아인님 실측 2026-08-13).
    """
    return AdBrief(
        goal="copy",
        product=product,
        price=price,
        situation="신메뉴 출시",
        tone="따뜻하고 담백하게",
    )


def report(result: EvaluationResult, counter: FailureCounter, elapsed: float) -> None:
    total = len(result.persona_comments) + result.excluded_cnt
    rate = result.excluded_cnt / total * 100 if total else 0.0

    print(f"\n{'=' * 62}")
    print(f"  탈락률  {result.excluded_cnt}/{total} = {rate:.1f}%")
    print(f"  소요    {elapsed:.1f}초  (예산 30초, 콜 상한 {MAX_EVAL_CALLS})")
    print(f"{'=' * 62}")
    print(f"  스키마 실패 {counter.schema}회 · 근거 대조 실패 {counter.evidence}회")
    if result.excluded_ids:
        print(f"  탈락 페르소나: {', '.join(result.excluded_ids)}")
    print()
    print(f"  점수      {result.scores}")
    print(f"  신뢰도    {result.confidence} (표준편차 {result.max_metric_std})")
    for reason in result.confidence_reasons:
        print(f"            └ {reason}")
    print(f"  저항 요인 {result.top_resistance}")
    print(f"  출처      {result.area_nm} {result.quarter}")
    print()
    print("  개선 제안")
    for s in result.suggestions or ["(없음)"]:
        print(f"    · {s}")
    print()
    print("  손님 코멘트 (가중치순)")
    for c in result.persona_comments:
        mark = "△" if c.is_boundary else " "
        print(f"    {mark} {c.demo:<10} [{c.resistance:<9}] {c.comment}")

    if counter.samples:
        print("\n  탈락 로그 (최대 5건)")
        for line in counter.samples:
            print(f"    · {line}")


def report_stability(runs: list[EvaluationResult]) -> None:
    """같은 입력을 여러 번 돌렸을 때 점수가 얼마나 흔들리는가.

    `SIGMA_MAX` 를 임의값이 아니라 실측으로 정하기 위한 재료다.
    """
    print(f"\n{'=' * 62}")
    print(f"  재현성 — 같은 입력 {len(runs)}회")
    print(f"{'=' * 62}")
    for metric in ("attention", "message", "intent"):
        values = [r.scores[metric] for r in runs]
        spread = max(values) - min(values)
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        print(f"  {metric:<10} {values}  폭 {spread:.1f}  표준편차 {sd:.2f}")
    drops = [r.excluded_cnt for r in runs]
    print(f"  탈락 수     {drops}")


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 LLM 으로 패널 평가 1회 실행")
    parser.add_argument("--runs", type=int, default=1, help="같은 입력 반복 횟수")
    parser.add_argument("--no-summary", action="store_true", help="제안 요약 콜 끄기")
    parser.add_argument(
        "--price", type=int, default=9500, help="광고 가격. 0 이면 가격 없는 광고"
    )
    parser.add_argument("--product", default="크로플", help="광고 상품명")
    parser.add_argument("--headline", default=SAMPLE_HEADLINE, help="광고 헤드라인")
    parser.add_argument("--sub", default=SAMPLE_SUB, help="광고 서브카피")
    args = parser.parse_args()

    load_env()
    profile = os.environ.get("MODEL_PROFILE", "stub")
    if profile != "openai":
        print(f"MODEL_PROFILE 이 {profile!r} 입니다. 실제 호출을 하려면:")
        print("  MODEL_PROFILE=openai python eval/run_panel_eval.py")
        return 1

    panel = load_panel()
    # 자기일관성(k)이 켜져 있으면 남는 예산만큼 더 물어본다. 상한이 있으니
    # 실제 콜은 `MAX_EVAL_CALLS` 를 넘지 않는다.
    follow_up = 1 + (0 if args.no_summary else 1)
    per_run = min(MAX_EVAL_CALLS, len(panel.personas) + follow_up)
    print(f"페르소나 {len(panel.personas)}명 · {args.runs}회 실행")
    print(f"예상 콜 {per_run * args.runs}회 (재시도 제외) — 팀 공용 키를 씁니다.\n")

    counter = FailureCounter()
    logger = logging.getLogger("app_core.panel.evaluator")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(counter)

    store, brief = sample_store(), sample_brief(args.price, args.product)
    copy = CopyCandidate(headline=args.headline, sub=args.sub)
    if not brief.show_price:
        print("※ 주문서에 가격이 없습니다 — 손님에게 `avg_ticket` 을 보여주지 않습니다.\n")
    if args.product not in args.headline + args.sub:
        print(f"⚠️ 문구에 '{args.product}' 이(가) 없습니다. 입력이 어긋나면 결과를 못 믿습니다.\n")
    results: list[EvaluationResult] = []

    for i in range(args.runs):
        started = time.perf_counter()
        try:
            result = evaluate(
                panel,
                store,
                brief,
                copy,
                ad_id=f"trial-{i + 1}",
                summarize=not args.no_summary,
            )
        except AggregationError as exc:
            print(f"[{i + 1}회] 전원 탈락 — {exc}")
            print("  프롬프트가 지시를 못 따르고 있습니다. 로그를 보세요.")
            for line in counter.samples:
                print(f"    · {line}")
            return 2
        elapsed = time.perf_counter() - started
        if args.runs > 1:
            print(f"\n───── {i + 1}회 ─────")
        report(result, counter, elapsed)
        results.append(result)

    if len(results) > 1:
        report_stability(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
