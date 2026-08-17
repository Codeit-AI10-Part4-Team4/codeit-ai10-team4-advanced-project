"""패널 제안이 광고를 **실제로 낫게 만드는가** — 재생성 루프 A/B 측정.

어제 루프가 **도는 것**은 확인했다. **낫게 만드는지**는 확인하지 못했다.
그게 이 제품의 핵심 주장이라 비워둘 수 없다.

심판은 `contrast.py` 의 `fit` 이다. LLM 이 아니라 서울시 실측 수치로 뺄셈·나눗셈
하는 결정적 함수라 **자기가 만든 것을 자기가 칭찬할 수 없다.** LLM 에게
"좋아졌니?" 라고 되묻는 순환 평가를 피하는 것이 이 설계의 전부다.

**개선과 회피를 가른다.**

    개선  시점을 손님 있는 쪽으로 옮겼다     → fit 오름, 채점 항목 유지
    회피  시점 언급을 지워 감점을 피했다      → fit 오름, 채점 항목 사라짐

둘 다 점수는 오른다. `weakest()` 가 `fit is None` 인 항목을 빼고 최솟값을 고르기
때문에 **항목을 지운 광고가 유리해진다** (`contrast.py` 의 `weakest` 독스트링이
평균을 버린 이유와 같은 함정이다). 안 가르면 "효과 있음"이라는 틀린 결론이 난다.

**대조군을 둔다.** 패널 제안 대신 사장님 선택지("아예 다른 느낌으로")로 재생성한다.
이게 없으면 *재생성 자체*의 효과와 *패널*의 효과를 구분할 수 없다.

    MODEL_PROFILE=openai python eval/run_ab_panel.py
    MODEL_PROFILE=openai python eval/run_ab_panel.py --out ab.json --stores 1

⚠️ 실제 OpenAI 호출이 나간다 (실행 끝에 실측 호출 수를 찍는다).
DuckDB 상권 데이터가 필요하다 — 없으면 `PANEL_DB` 로 경로를 준다.

⚠️ **PR #8(`feat/chatbot-flow-prototype`) 머지 전에는 import 가 실패한다.**
재생성 루프(`schema.Feedback`·`AdBrief.revised()`)가 그 PR 에 있다. 측정을 그
브랜치에서 돌렸으므로 결과(`ab_panel.json`)는 유효하고, 스크립트를 여기 먼저
두는 이유는 그 결과를 재현할 방법 없이 결론만 남기지 않기 위해서다.
`eval/` 은 CI 범위 밖이라(pytest `testpaths=["tests"]`, mypy `files=["src"]`)
이 상태가 검사를 깨지는 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app_core.config import load_env
from app_core.copy_gen import generate
from app_core.llm import get_client
from app_core.panel.contrast import contrast, weakest
from app_core.panel.features import build_features
from app_core.panel.review import review
from app_core.panel.schemas import TradeAreaFeatures
from app_core.schema import AdBrief, CopyCandidate, Feedback, Store

#: 좌표를 박아두면 카카오 지오코딩을 건너뛴다 — 호출이 줄고 매번 같은 상권이 나온다.
#: 홍대·수유는 테스트에서 쓰던 값 그대로다.
STORES: list[tuple[Store, tuple[float, float]]] = [
    (
        Store(id=1, user_id=1, industry="cafe", name="한나절커피", address="서울 강남구 역삼동"),
        (127.0364, 37.5006),
    ),
    (
        Store(
            id=2, user_id=1, industry="korean_food", name="홍대반상", address="서울 마포구 서교동"
        ),
        (126.9250, 37.5610),
    ),
    (
        Store(id=3, user_id=1, industry="chicken", name="수유통닭", address="서울 강북구 수유동"),
        (127.0155, 37.6893),
    ),
]

#: 사장님이 실제로 낼 법한 평범한 광고. **일부러 어긋나게 만들지 않았다** —
#: 고칠 게 많은 광고만 고르면 개선폭이 부풀려져 결과를 믿을 수 없다.
BRIEFS: dict[str, list[dict[str, Any]]] = {
    "cafe": [
        {
            "product": "아이스 아메리카노",
            "price": 4500,
            "situation": "여름 시즌 음료",
            "tone": "시원한",
        },
        {"product": "크로플 세트", "price": 8900, "situation": "신메뉴 출시", "tone": "친근한"},
        {"product": "원두 드립백", "price": 12000, "situation": "선물용 상품", "tone": "차분한"},
    ],
    "korean_food": [
        {"product": "김치찌개", "price": 9000, "situation": "점심 특선", "tone": "푸근한"},
        {"product": "제육볶음 정식", "price": 11000, "situation": "신메뉴 출시", "tone": "힘있는"},
        {"product": "계란말이", "price": 6000, "situation": "사이드 메뉴 추가", "tone": "가벼운"},
    ],
    "chicken": [
        {"product": "후라이드 치킨", "price": 18000, "situation": "창업 3주년", "tone": "신나는"},
        {"product": "양념치킨 세트", "price": 25000, "situation": "주말 할인", "tone": "활기찬"},
        {"product": "순살 반반", "price": 22000, "situation": "배달 전용 메뉴", "tone": "간결한"},
    ],
}

#: 대조군 피드백. 패널이 준 내용이 아니라 `copy_gen.REVISION_OPTIONS` 의 선택지다.
CONTROL_NOTES = ["아예 다른 느낌으로"]


class Counting:
    """실제 OpenAI 호출 수를 **센다**. 추정하지 않는다.

    `evaluate` 가 손님 12명을 스레드로 병렬 호출하므로 카운터에 락이 필요하다.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self.n = 0

    def complete_json(self, system: str, user: str) -> dict:
        with self._lock:
            self.n += 1
        return self._inner.complete_json(system, user)


def score(feats: TradeAreaFeatures, brief: AdBrief, copy: CopyCandidate) -> dict[str, Any]:
    """광고 하나의 채점표.

    `weak` 만 남기면 회피를 못 잡는다. **무엇을 채점했는지**(`scored`)를 같이 남긴다.
    """
    notes = contrast(feats, brief, copy)
    w = weakest(notes)
    return {
        "headline": copy.headline,
        "sub": copy.sub,
        "weak": None if w is None else round(w.fit or 0.0, 4),
        "weak_kind": None if w is None else w.kind,
        # 채점된 항목만 담는다. 여기서 항목이 사라지면 회피 후보다.
        "scored": {n.kind: round(n.fit or 0.0, 4) for n in notes if n.fit is not None},
    }


#: 이보다 작은 변화는 흔들림으로 본다. `fit` 은 0~1 이라 0.01 은 1%p 다.
NOISE = 0.01


def verdict(before: dict[str, Any], after: dict[str, Any]) -> str:
    """개선인가 회피인가.

    채점 항목이 하나라도 사라졌으면 점수가 올라도 개선이라 부르지 않는다.

    **천장에 붙은 표본은 따로 뺀다.** `fit` 은 1.0 이 만점이라 시작점이 이미 1.0
    이면 `a > b + NOISE` 가 성립할 수 없다 — 무엇을 해도 "변화 없음"이 나온다.
    그대로 세면 *못 잰 것*이 *효과 없음*으로 읽힌다. 1차 측정(9건)이 실제로 그랬다:
    `before.weak` 가 1.0 인 표본이 6건이었는데 패널·대조군이 나란히 "변화 없음 8/9"
    라, 표만 보면 패널이 아무 값도 못 한 것처럼 보인다.

    천장이 예외가 아니라 **기본값**이라는 것은 나중에 알았다. `_price_fit` 은
    가격이 객단가 이하면 1.0 을 주고(싼 쪽은 감점하지 않는다), 시점·주말을 말하지
    않은 광고는 채점 항목이 `price` 하나뿐이다. 즉 평범한 광고일수록 천장에 붙는다.
    다시 잴 때는 **약점이 있는 광고로 표본을 골라야** 한다.
    """
    lost = sorted(set(before["scored"]) - set(after["scored"]))
    b, a = before["weak"], after["weak"]
    if b is None or a is None:
        return "잴 수 없음"
    if b >= 1.0 - NOISE:
        return "천장(잴 수 없음)"
    if lost:
        return ("회피" if a > b + NOISE else "항목 사라짐") + f"({','.join(lost)})"
    if a > b + NOISE:
        return "개선"
    if a < b - NOISE:
        return "악화"
    return "변화 없음"


def _arm(
    brief: AdBrief,
    base: CopyCandidate,
    store: Store,
    feats: TradeAreaFeatures,
    source: str,
    notes: list[str],
    resistance: list[str],
) -> dict[str, Any] | None:
    """재생성 한 갈래. 제안이 없으면 재생성할 이유가 없으므로 None."""
    if not notes:
        return None
    rev = brief.revised(
        Feedback(source=source, notes=list(notes), resistance=list(resistance)),  # type: ignore[arg-type]
        [base],
    )
    new = generate(rev, store)
    return score(feats, rev, new[0]) if new else None


def run(limit: int) -> list[dict[str, Any]]:
    client = Counting(get_client())
    rows: list[dict[str, Any]] = []

    for store, coord in STORES[:limit]:
        feats = TradeAreaFeatures(**build_features(store.address, store.industry, coord=coord))
        print(f"\n=== {store.name} / {feats.area_nm} / {feats.category_nm} ===", flush=True)

        for i, spec in enumerate(BRIEFS[store.industry]):
            t0 = time.time()
            brief = AdBrief(goal="copy", **spec)

            copies = generate(brief, store)
            if not copies:
                print(f"  [{i}] {spec['product']}: 생성 실패 — 후보 0건", flush=True)
                continue
            base = copies[0]
            before = score(feats, brief, base)

            # 패널에 물어본다. 호출의 대부분이 여기서 나간다.
            ev = review(store, brief, base, ad_id=f"{store.id}-{i}", coord=coord, client=client)

            panel = _arm(
                brief, base, store, feats, "panel", list(ev.suggestions), list(ev.top_resistance)
            )
            control = _arm(brief, base, store, feats, "option", CONTROL_NOTES, [])

            row = {
                "store": store.name,
                "area": feats.area_nm,
                "category": feats.category_nm,
                "product": spec["product"],
                "price": spec["price"],
                "before": before,
                "suggestions": list(ev.suggestions),
                "top_resistance": list(ev.top_resistance),
                "confidence": ev.confidence,
                "excluded_cnt": ev.excluded_cnt,
                "panel": panel,
                "control": control,
                "verdict_panel": verdict(before, panel) if panel else "제안 없음",
                "verdict_control": verdict(before, control) if control else "-",
                "secs": round(time.time() - t0, 1),
            }
            rows.append(row)
            print(
                f"  [{i}] {spec['product']}: "
                f"{before['weak']}({before['weak_kind']}) → "
                f"패널 {panel and panel['weak']} [{row['verdict_panel']}] / "
                f"대조 {control and control['weak']} [{row['verdict_control']}]  {row['secs']}s",
                flush=True,
            )

    print(f"\n실제 OpenAI 호출: {client.n}회", flush=True)
    return rows


def summary(rows: list[dict[str, Any]]) -> None:
    """판정별 집계. 표본이 작으므로 비율이 아니라 **건수**로 쓴다."""
    for arm in ("panel", "control"):
        tally: dict[str, int] = {}
        for r in rows:
            key = r[f"verdict_{arm}"].split("(")[0]
            tally[key] = tally.get(key, 0) + 1
        line = " / ".join(f"{k} {v}" for k, v in sorted(tally.items()))
        print(f"{arm:8s} (n={len(rows)}): {line}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="ab_panel.json")
    ap.add_argument("--stores", type=int, default=len(STORES), help="앞에서 몇 곳만 돌릴지")
    args = ap.parse_args()

    load_env()
    rows = run(args.stores)
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    summary(rows)
    print(f"저장: {args.out}")
