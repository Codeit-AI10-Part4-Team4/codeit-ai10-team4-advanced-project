"""나쁜 광고가 **왜** 나쁜지 제대로 짚는가 — 걸림돌 라벨 회귀 검사.

`accuracy.py` 는 좋은 광고가 나쁜 광고보다 **높은 점수**를 받는지 본다.
그런데 사장님 화면에 뜨는 것은 점수만이 아니라 **"무엇이 걸렸는지"** 다.
`accuracy.py` 도 걸림돌 분포를 표로 찍기는 하는데 **합불을 가르지 않아서**,
사람이 표를 보고 알아채야 한다. 아무도 안 봤다.

    "10대 필수템 크로플 / 학교 끝나고 친구랑"   (역삼 = 직장인 93.6%)
    → 정답은 relevance 인데 alternative 가 1위로 나오는 일이 있다 (2026-08-18).

점수 순위는 맞아서 `accuracy.py` 는 통과한다. 라벨만 틀린다.
**여기가 그 구멍을 막는다.**

광고를 새로 만들지 않는다 — `accuracy.PAIRS` 를 그대로 쓴다. 같은 광고를 두 군데
적어두면 한쪽만 고쳐져 어긋난다.

## 한 번만 재면 안 된다 (이게 이 파일에서 제일 중요하다)

만들면서 `target_bad` 를 1회씩 세 번 쟀는데 답이 갈렸다 (2026-08-18, 전부 같은 코드):

    실경로 A     alternative   틀림
    실경로 B     relevance     맞음
    픽스처       relevance     맞음

**처음엔 픽스처가 결함을 가린다고 결론냈다가 틀렸다.** 경로 차이가 아니라
실행 간 흔들림이었다. 그래서 `--runs 3` 으로 다시 쟀다:

    광고          기대        기대 라벨의 비중   맞은 횟수
    price_bad    price              100%        3/3   ← 확실히 맞다
    target_bad   relevance           14%        0/3   ← 위 "맞음"이 소수였다
    clear_bad    message              0%        0/3   ← 아예 안 나온다

1회로는 `target_bad` 가 맞아 보였지만 3회로는 0/3 이다. **1회 결과로 "고쳤다/
망가졌다"를 말하면 안 된다** — `accuracy.py` 도 같은 이유로 "3점 안쪽 차이는
해석하지 말라"고 적어두고 있다.

그래서 이 스크립트는 **기대 라벨의 비중을 같이 찍고**(0% 인지 14% 인지가
"아예 없다"와 "밀려 있다"를 가른다), `--runs` 로 여러 번 돌려 과반으로 판정한다.

    MODEL_PROFILE=openai python eval/run_label_check.py                # 1회 (빠른 눈대중)
    MODEL_PROFILE=openai python eval/run_label_check.py --runs 3       # 판정하려면 이쪽
    MODEL_PROFILE=openai python eval/run_label_check.py --fixture      # DuckDB 없이

⚠️ 실제 호출이 나간다 — 광고 4개 × (손님 12명 + 분류 + 서사) ≈ **1회당 56콜**.
`--runs 3` 이면 약 168콜이다. CI 에 넣지 않는다 (팀 규칙상 테스트는 mock 만 쓴다,
AGENTS.md). **프롬프트나 걸림돌 로직을 고친 뒤 사람이 한 번 돌리는** 자리다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from accuracy import PAIRS, Ad, load_panel, sample_store

from app_core.config import load_env
from app_core.panel import review as review_mod
from app_core.panel.aggregate import AggregationError
from app_core.panel.evaluator import evaluate
from app_core.panel.review import review

#: 역삼역. 넘기면 카카오 지오코딩을 건너뛴다.
YEOKSAM = (127.0365, 37.5005)

#: 나쁜 광고마다 **어떤 걸림돌이 나와야 하는지.** 사람이면 이견이 없는 것만 넣는다.
#:
#: `time_bad`("새벽 감성 크로플")는 **일부러 뺐다.** 시점이 어긋난 것은 맞지만
#: 라벨 다섯 개(none·relevance·alternative·message·price) 중 어디로 가야 하는지
#: 사람도 갈린다. 답이 갈리는 것을 정답으로 박아두면 통과해도 무의미하고
#: 틀려도 원인을 모른다.
EXPECT: dict[str, str] = {
    "price_bad": "price",  # 9,546원 동네에 45,000원 — 값이 부담이다
    "target_bad": "relevance",  # 직장인 93.6% 동네에 "10대 필수템" — 나와 상관없다
    "clear_bad": "message",  # "당신의 순간을 위하여" — 무엇을 파는지 모른다
}

#: 판정하지 않고 눈으로만 보는 것. 이유를 적어둬야 나중에 "왜 뺐지"가 안 생긴다.
WATCH: dict[str, str] = {
    "time_bad": "시점 어긋남 — 담을 라벨이 없어 정답을 못 정한다",
}


def _ads() -> list[Ad]:
    """검사 대상은 **나쁜 쪽만**이다.

    좋은 광고에 `none` 이 나와야 하는 것 아니냐 싶지만, 지금은 12명 전원이
    `price` 를 고른다(2026-08-18 실측). 못 고치는 것을 빨간불로 박아두면
    사람이 빨간불을 무시하게 된다 — 그건 검사가 없느니만 못하다.
    좋은 광고의 라벨 분포는 `accuracy.py` 표에 이미 찍힌다.
    """
    return [p.worse for p in PAIRS]


class Tally:
    """광고 하나를 여러 번 잰 결과."""

    def __init__(self, ad: Ad) -> None:
        self.ad = ad
        self.want = EXPECT.get(ad.key)
        self.tops: list[str] = []  # 회차별 1위 라벨
        self.shares: list[float] = []  # 회차별 기대 라벨의 비중

    def add(self, top: list[str], share: dict[str, float]) -> None:
        self.tops.append(top[0] if top else "없음")
        self.shares.append(share.get(self.want or "", 0.0))

    @property
    def hits(self) -> int:
        return sum(t == self.want for t in self.tops)

    @property
    def verdict(self) -> str | None:
        """과반이면 맞음. 판정 대상이 아니면 None."""
        if self.want is None:
            return None
        if self.hits * 2 > len(self.tops):
            return "맞음" if self.hits == len(self.tops) else "맞음(흔들림)"
        # 아예 안 나온 것과 2위로 밀린 것은 원인이 다르다.
        never = all(s == 0.0 for s in self.shares)
        return "틀림(아예 없음)" if never else "틀림(밀려 있음)"


def _run_once(ad: Ad, panel, store, *, k: int, fixture: bool):
    if fixture:
        return evaluate(panel, store, ad.brief, ad.copy, ad_id=ad.key, consistency_k=k)
    return review(store, ad.brief, ad.copy, ad_id=ad.key, coord=YEOKSAM, consistency_k=k)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=1, help="같은 광고를 몇 번 잴지 (판정은 과반)")
    ap.add_argument("--k", type=int, default=1, help="자기일관성 표본 수")
    ap.add_argument("--fixture", action="store_true", help="DuckDB 없이 골든 픽스처로")
    args = ap.parse_args()

    load_env()
    panel, store = load_panel(), sample_store()
    ads = _ads()
    per_ad = len(panel.personas) + 1 + (0 if args.fixture else 1)
    where = "픽스처" if args.fixture else "실경로"
    print(
        f"광고 {len(ads)}개 × {args.runs}회 · 콜 최대 {len(ads) * per_ad * args.runs}회 · {where}"
    )
    if args.runs == 1:
        print("  ⚠️ 1회는 눈대중이다. 걸림돌 1위는 실행마다 갈린다 — 판정하려면 --runs 3\n")
    else:
        print()

    tallies = [Tally(ad) for ad in ads]
    for run in range(args.runs):
        # `review` 는 같은 광고를 다시 평가하지 않는다(재현성 보장 캐시).
        # 여기서는 흔들림 자체를 재는 것이 목적이라 회차마다 비운다.
        review_mod._CACHE.clear()
        for t in tallies:
            try:
                res = _run_once(t.ad, panel, store, k=args.k, fixture=args.fixture)
            except AggregationError as exc:
                print(f"  [{t.ad.key}] 전원 탈락 — {exc}")
                return 2
            t.add(list(res.top_resistance), dict(res.resistance_share))
        print(f"  {run + 1}회차 완료")

    print(f"\n{'=' * 78}")
    print(f"  {'광고':<12} {'나와야 할 것':<12} {'비중':>7}  {'맞은 횟수':>9}  판정")
    print(f"{'=' * 78}")
    failed = 0
    for t in tallies:
        verdict = t.verdict
        share = sum(t.shares) / len(t.shares)
        if verdict is None:
            line = f"  {t.ad.key:<12} {'-':<12} {'':>7}  {'':>9}  관찰 ({t.tops[0]})"
        else:
            if verdict.startswith("틀림"):
                failed += 1
            line = (
                f"  {t.ad.key:<12} {t.want:<12} {share:>6.0%}  "
                f"{t.hits:>4}/{len(t.tops):<4}  {verdict}"
            )
        print(line)
        print(f"  {'':<12} {t.ad.copy.headline}")
    print(f"{'=' * 78}")

    for key, why in WATCH.items():
        print(f"  ※ {key} 는 판정하지 않는다 — {why}")

    if failed:
        print(f"\n  {failed}개가 틀렸다. 걸림돌이 광고를 안 보고 정해지고 있다.")
        print("  라벨 정의만 있고 **예시가 없는 라벨**부터 의심하라 —")
        print("  2026-08-18 에 relevance 가 정확히 그래서 흔들렸다(예시 4줄 중 0줄).")
        return 1

    print("\n  전부 맞음. 나쁜 광고가 왜 나쁜지 제대로 짚고 있다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
