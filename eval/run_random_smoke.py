"""무작위 상권 × 무작위 업종으로 패널이 만들어지는지 끝까지 돌려본다.

**좌표를 박지 않는다.** 이번 사고(2026-08-19)의 원인이 정확히 그것이었다 —
관통 실행을 역삼·홍대·수유 세 곳에서만 했고 그 셋은 전 연령대에 매출이
있어서, `age_share` 의 어떤 칸이 0 인 상권에서 `Persona.weight` 의 `gt=0.0`
에 걸려 죽는 것을 아무도 못 봤다. **주소 × 업종 50,016 조합 중 20.9%** 가
그 상태였고, 화면에서는 사장님에게 빨간 트레이스백이 그대로 떴다.

테스트 679 개가 전부 통과하고 있었다. 통과한 게 아니라 **그 경우를 본 적이
없었던 것**이다. 골든 픽스처도 역삼역 하나뿐이라 같은 눈을 갖고 있다.

    python eval/run_random_smoke.py                 # 60 조합 · API 0 콜
    python eval/run_random_smoke.py --n 200         # 넓게
    python eval/run_random_smoke.py --seed 7        # 다시 같은 조합으로
    MODEL_PROFILE=openai python eval/run_random_smoke.py --n 3 --llm   # 평가까지

**기본값은 LLM 을 안 쓴다.** 이번 사고는 첫 콜이 나가기도 전에 터졌으므로
스텁으로도 잡힌다. 팀 예산이 공용이라, 돈 드는 검사는 사람이 켜야 돌게 둔다.

카카오 키도 필요 없다 — 상권 좌표를 DB 에서 그대로 읽는다.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app_core import registry
from app_core.panel.features import DB_PATH, NoTradeAreaError, build_features
from app_core.panel.panel_builder import build_panel
from app_core.panel.schemas import Panel


def areas(n: int, rng: random.Random) -> list[tuple[str, str, float, float]]:
    """상권 표를 통째로 읽어 무작위로 고른다."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = con.execute("SELECT area_cd, area_nm, lon, lat FROM area").fetchall()
    finally:
        con.close()
    return rng.sample(rows, min(n, len(rows)))


def one(area: tuple[str, str, float, float], industry: str) -> tuple[str, str]:
    """한 조합을 돌린다. `(결과, 설명)` 을 돌려준다."""
    _, name, lon, lat = area
    try:
        f = build_features("", industry, coord=(lon, lat))
        seeds = build_panel(f)
        panel = Panel.model_validate({"features": f, "personas": seeds})
    except NoTradeAreaError:
        # 상권을 못 찾은 것은 결함이 아니다 — 폴백이 설계대로 도는 자리다.
        return "폴백", ""
    except Exception as exc:  # noqa: BLE001 — 무엇이 터지는지 세는 것이 목적이다
        return type(exc).__name__, f"{name} × {registry.label_of(industry)}: {exc}"
    return "정상", f"{len(panel.personas)}명"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=60, help="돌려볼 조합 수")
    ap.add_argument("--seed", type=int, default=0, help="같은 조합을 다시 뽑으려면")
    ap.add_argument("--llm", action="store_true", help="평가까지 (실제 API · 조합당 14콜)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"상권 데이터가 없습니다 ({DB_PATH}).")
        return 2

    rng = random.Random(args.seed)
    inds = sorted(registry.industry_ids() - {registry.OTHER})
    picked = areas(args.n, rng)

    print(f"상권 {len(picked)}곳 × 무작위 업종 · seed {args.seed}")
    print(f"API {'사용' if args.llm else '미사용'}\n")

    tally: Counter[str] = Counter()
    sizes: Counter[int] = Counter()
    broken: list[str] = []

    for area in picked:
        kind, detail = one(area, rng.choice(inds))
        tally[kind] += 1
        if kind == "정상":
            sizes[int(detail.rstrip("명"))] += 1
        elif kind != "폴백":
            broken.append(f"[{kind}] {detail}")

    print(f"{'=' * 74}")
    for kind, cnt in tally.most_common():
        mark = "  " if kind in ("정상", "폴백") else "❌"
        print(f"  {mark} {kind:<24} {cnt:>4} / {len(picked)}  ({cnt / len(picked):.0%})")
    if sizes:
        detail = " · ".join(f"{k}명 {v}곳" for k, v in sorted(sizes.items(), reverse=True))
        print(f"\n  패널 크기   {detail}")
        if len(sizes) > 1:
            print("  (12명이 아닌 곳이 있다 — 매출 0 인 연령대는 손님으로 안 만든다)")
    print(f"{'=' * 74}")

    if broken:
        print(f"\n  터진 곳 {len(broken)}건 (최대 8건):")
        for line in broken[:8]:
            print(f"    · {line}")
        print("\n  좌표를 박아둔 곳에서만 돌리면 이 결함이 안 보인다.")
        print("  픽스처를 늘릴 때 여기서 나온 상권을 넣어라.")
        return 1

    print("\n  전부 완주. 무작위 상권에서도 패널이 만들어진다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
