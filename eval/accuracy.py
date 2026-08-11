"""패널이 **좋은 광고와 나쁜 광고를 구분하는가**를 잰다.

정확도를 못 재면 개선을 말할 수 없다. 그런데 "실제 손님 반응"이라는 정답은
우리에게 없다. 그래서 정답 대신 **순서**를 쓴다 — 어느 쪽이 나은지 사람이면
이견 없이 답할 수 있는 광고 쌍을 만들어, 패널이 그 순서를 맞추는지 본다.

    MODEL_PROFILE=openai python eval/accuracy.py            # 판별력 (라벨 불필요)
    MODEL_PROFILE=openai python eval/accuracy.py --sheet    # 사람 평가용 시트 만들기
    MODEL_PROFILE=openai python eval/accuracy.py --score labels.csv   # 사람과 대조

**판별력이 낮으면 점수는 노이즈다.** 쌍을 못 가르는데 절대 점수가 62.4 라고
말하는 것은 의미가 없다. 이 지표가 먼저다.

쌍은 **역삼역 실측에 근거해서만** 만든다. 점심 매출 47.9%, 객단가 9,546원,
30대 38.2% — 이 숫자에서 벗어난 광고가 "나쁜 쪽"이다. 취향으로 만든 쌍은
패널이 틀려도 패널 탓인지 우리 탓인지 알 수 없다.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from panel_metrics import mean_absolute_error, pearson, spearman

from app_core.config import load_env
from app_core.panel.aggregate import AggregationError
from app_core.panel.evaluator import evaluate
from app_core.panel.schemas import EvaluationResult, Panel
from app_core.schema import AdBrief, CopyCandidate, Store, StoreInput

FIXTURE = ROOT / "tests" / "fixtures" / "features_yeoksam_20261.json"


class Ad(NamedTuple):
    key: str
    brief: AdBrief
    copy: CopyCandidate


class Pair(NamedTuple):
    """`better` 가 `worse` 보다 높은 점수를 받아야 한다.

    `kind` 가 `"상권"` 인 쌍만 역삼 실측에 근거한다. `"보편"` 쌍은 어느 동네든
    참인 성질(무엇을 파는지 알겠는가)이라 상권 그라운딩과는 다른 것을 잰다 —
    틀렸을 때 "이 동네 데이터가 프롬프트에 안 들어갔다"로 해석하면 안 된다.
    둘을 섞어서 하나의 정확도로 보고하면 원인을 잘못 짚게 된다.
    """

    name: str
    kind: str
    why: str
    better: Ad
    worse: Ad


def _ad(key: str, product: str, price: int, headline: str, sub: str = "") -> Ad:
    return Ad(
        key,
        AdBrief(goal="copy", product=product, price=price, situation="신메뉴"),
        CopyCandidate(headline=headline, sub=sub),
    )


#: 역삼역 커피-음료 2026Q1 실측에서 나온 쌍. 각 쌍은 **한 가지만** 다르다 —
#: 여러 개를 바꾸면 무엇 때문에 갈렸는지 알 수 없다.
PAIRS: list[Pair] = [
    Pair(
        "시간대",
        "상권",
        "점심 매출 47.9% vs 새벽 0.1%",
        _ad("time_good", "크로플", 9500, "점심 10분 컷, 크로플", "주문하고 자리 잡으면 나옵니다"),
        _ad("time_bad", "크로플", 9500, "새벽 감성 크로플", "해 뜨기 전에 드세요"),
    ),
    Pair(
        "가격",
        "상권",
        "동네 객단가 9,546원 — 45,000원은 4.7배",
        _ad("price_good", "크로플", 9500, "오늘의 크로플", "갓 구워 냅니다"),
        _ad("price_bad", "크로플", 45000, "오늘의 크로플", "갓 구워 냅니다"),
    ),
    Pair(
        "타깃",
        "상권",
        "30대 38.2%, 직장인 비율 93.6% — 10대 겨냥은 이 동네에 없다",
        _ad("target_good", "크로플", 9500, "퇴근길에 하나", "혼자 먹기 딱 좋은 크기"),
        _ad("target_bad", "크로플", 9500, "10대 필수템 크로플", "학교 끝나고 친구랑"),
    ),
    Pair(
        "명료성",
        "보편",
        "무엇을 파는지 알 수 있는가 (동네와 무관한 기본기)",
        _ad("clear_good", "크로플", 9500, "겉바속촉 크로플 9,500원", "매일 오전에 굽습니다"),
        _ad("clear_bad", "크로플", 9500, "당신의 순간을 위하여", "그 감성 그대로"),
    ),
]


def load_panel() -> Panel:
    with FIXTURE.open(encoding="utf-8") as fp:
        return Panel.model_validate(json.load(fp))


def sample_store() -> Store:
    base = StoreInput(industry="cafe", name="역삼 크로플", address="서울시 강남구 역삼동 823")
    return Store(**base.model_dump(), id=1, user_id=1)


def _mean_score(result: EvaluationResult) -> float:
    return statistics.fmean(result.scores.values())


def run_pairs(k: int) -> int:
    panel, store = load_panel(), sample_store()
    per_ad = len(panel.personas) + 1
    print(f"쌍 {len(PAIRS)}개 · 광고 {len(PAIRS) * 2}개 · 콜 최대 {len(PAIRS) * 2 * per_ad}회\n")

    scores: dict[str, EvaluationResult] = {}
    for pair in PAIRS:
        for ad in (pair.better, pair.worse):
            try:
                scores[ad.key] = evaluate(
                    panel, store, ad.brief, ad.copy, ad_id=ad.key, consistency_k=k
                )
            except AggregationError as exc:
                print(f"  [{ad.key}] 전원 탈락 — {exc}")
                return 2

    print(f"{'=' * 74}")
    print(f"  {'쌍':<8} {'좋은 쪽':>8} {'나쁜 쪽':>8} {'차이':>8}   판정   근거")
    print(f"{'=' * 74}")

    wins, gaps = 0, []
    for pair in PAIRS:
        good, bad = _mean_score(scores[pair.better.key]), _mean_score(scores[pair.worse.key])
        gap = good - bad
        gaps.append(gap)
        hit = gap > 0
        wins += hit
        print(
            f"  {pair.name:<8} {good:>8.1f} {bad:>8.1f} {gap:>+8.1f}   "
            f"{'맞음' if hit else '틀림'}   {pair.why}"
        )

    print(f"{'=' * 74}")
    print(f"  판별 정확도  {wins}/{len(PAIRS)} = {wins / len(PAIRS) * 100:.0f}%")
    print(f"  평균 점수차  {statistics.fmean(gaps):+.1f}점")
    print()
    if wins < len(PAIRS):
        print("  틀린 쌍이 있다 — 그 축(시간대·가격·타깃·명료성)의 근거가")
        print("  프롬프트에 충분히 들어가지 않았을 수 있다.")
    if statistics.fmean(gaps) < 5:
        print("  점수차가 5점 미만이다. 순서는 맞아도 실제로는 구별하지 못하는 것에")
        print("  가깝다 — 척도 앵커나 표본 수를 손봐야 한다.")
    return 0


SHEET_COLUMNS = ["ad_key", "headline", "sub", "price", "사람점수_0_100"]


def make_sheet(path: Path) -> int:
    """사람이 블라인드로 채울 시트. 순서를 섞어 광고 키를 감춘다."""
    import random

    ads = [ad for pair in PAIRS for ad in (pair.better, pair.worse)]
    random.Random(0).shuffle(ads)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(SHEET_COLUMNS)
        for ad in ads:
            writer.writerow([ad.key, ad.copy.headline, ad.copy.sub, ad.brief.price, ""])
    print(f"{path} 를 만들었습니다. 팀원들이 각자 채운 뒤:")
    print(f"  MODEL_PROFILE=openai python eval/accuracy.py --score {path}")
    print("\n채울 때 규칙 — 광고만 보고 0~100 으로 매기세요.")
    print("  0~20 그냥 지나침 / 41~60 괜찮네 / 81~100 지금 가고 싶다")
    return 0


def score_against_humans(path: Path, k: int) -> int:
    with path.open(encoding="utf-8-sig") as fp:
        rows = [r for r in csv.DictReader(fp) if r.get("사람점수_0_100", "").strip()]
    if len(rows) < 3:
        print("사람 점수가 3건 미만입니다. 상관을 낼 수 없습니다.")
        return 1

    panel, store = load_panel(), sample_store()
    by_key = {ad.key: ad for pair in PAIRS for ad in (pair.better, pair.worse)}

    human, machine = [], []
    for row in rows:
        ad = by_key.get(row["ad_key"])
        if ad is None:
            continue
        result = evaluate(panel, store, ad.brief, ad.copy, ad_id=ad.key, consistency_k=k)
        human.append(float(row["사람점수_0_100"]))
        machine.append(_mean_score(result))

    print(f"\n  표본 {len(human)}건")
    print(f"  피어슨   {pearson(machine, human):+.3f}   (선형 일치)")
    print(f"  스피어만 {spearman(machine, human):+.3f}   (순위 일치 — 이쪽이 중요하다)")
    print(f"  평균오차 {mean_absolute_error(machine, human):.1f}점")
    print()
    print("  읽는 법: 스피어만 0.6 이상이면 '사람과 비슷한 순서로 본다'고 말할 수 있다.")
    print("  절대 점수(평균오차)는 척도가 달라 크게 나오는 것이 정상이다.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="패널 판별력·사람 대조 측정")
    parser.add_argument("--sheet", nargs="?", const="eval/labels.csv", metavar="CSV")
    parser.add_argument("--score", metavar="CSV")
    parser.add_argument("--k", type=int, default=1, help="자기일관성 표본 수")
    args = parser.parse_args()

    if args.sheet:
        return make_sheet(Path(args.sheet))

    load_env()
    if os.environ.get("MODEL_PROFILE") != "openai":
        print("MODEL_PROFILE=openai 로 실행하세요.")
        return 1

    if args.score:
        return score_against_humans(Path(args.score), args.k)
    return run_pairs(args.k)


if __name__ == "__main__":
    raise SystemExit(main())
