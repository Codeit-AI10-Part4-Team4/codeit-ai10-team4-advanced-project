"""상권 데이터 검수 — 적재된 DB와 **아직 안 받은 CSV** 둘 다 본다.

지금까지 검수를 일회용 스크립트로 하고 결과만 문서에 적었다. 그래서 같은
질문("표본이 몇 건부터 믿을 만한가")을 다시 물으면 매번 새로 짜야 했다.
여기 모아두면 집객시설·소득소비 CSV 를 받았을 때 같은 틀로 바로 돌린다.

    python etl/inspect_data.py                      # 적재된 DB 전체 검수
    python etl/inspect_data.py --csv "data/raw/*.csv"   # 새 CSV 실물 검수

**이 파일은 판정하지 않는다.** 숫자를 보여주고 사람이 판단한다 —
"이 값이 이상치인가"는 업종을 알아야 답할 수 있는 질문이라서다.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "panel.duckdb"

#: 결제 건수 구간. `features.MIN_SALES_CNT` 를 이 표를 보고 정했다.
CNT_BANDS = [(0, 30), (30, 100), (100, 300), (300, 1000), (1000, 5000), (5000, None)]


def _band(lo: int, hi: int | None) -> str:
    return f"{lo:,}~{hi - 1:,}" if hi else f"{lo:,}+"


def tables(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows = []
    for (t,) in con.execute("SHOW TABLES").fetchall():
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        cols = [r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()]
        q = (
            con.execute(f"SELECT DISTINCT quarter FROM {t} ORDER BY 1").fetchall()
            if "quarter" in cols
            else []
        )
        rows.append({"표": t, "행": n, "칸": len(cols), "분기": ",".join(x[0] for x in q) or "-"})
    return pd.DataFrame(rows)


def nulls_and_dupes(con: duckdb.DuckDBPyConnection, keys: dict[str, str]) -> pd.DataFrame:
    rows = []
    for t, key in keys.items():
        cols = [r[0] for r in con.execute(f"DESCRIBE {t}").fetchall()]
        nulls = sum(
            con.execute(f"SELECT count(*) FROM {t} WHERE {c} IS NULL").fetchone()[0] for c in cols
        )
        dup = con.execute(
            f"SELECT count(*) FROM (SELECT {key} FROM {t} GROUP BY ALL HAVING count(*) > 1)"
        ).fetchone()[0]
        rows.append({"표": t, "결측(전 칸 합)": nulls, "키 중복": dup})
    return pd.DataFrame(rows)


def ticket_stability(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """표본 수 구간별로 객단가가 업종 중앙값에서 얼마나 벗어나는가.

    편차가 표본 수에 따라 줄어들면, 적은 표본의 객단가는 못 믿는다는 뜻이다.
    큰 표본에서도 남는 편차는 **동네마다 객단가가 실제로 다른 것**이라
    더 낮출 수 없는 바닥이다.
    """
    rows = []
    for lo, hi in CNT_BANDS:
        cond = f"cnt >= {lo}" + (f" AND cnt < {hi}" if hi else "")
        r = con.execute(f"""
            WITH t AS (
              SELECT cnt, amount / cnt AS tick,
                     median(amount / cnt) OVER (PARTITION BY category_cd) AS med
              FROM sales WHERE cnt > 0)
            SELECT count(*), median(abs(tick - med) / med),
                   quantile_cont(abs(tick - med) / med, 0.9)
            FROM t WHERE med > 0 AND {cond}
        """).fetchone()
        rows.append(
            {
                "결제건수": _band(lo, hi),
                "행": r[0],
                "중앙편차": round(r[1] or 0, 3),
                "p90편차": round(r[2] or 0, 2),
            }
        )
    return pd.DataFrame(rows)


def ticket_extremes(con: duckdb.DuckDBPyConnection, n: int = 5) -> pd.DataFrame:
    """객단가 양 극단. 표본 수를 같이 봐야 이상치인지 실제인지 판단할 수 있다."""
    return con.execute(f"""
        SELECT a.area_nm 상권, s.category_cd 업종코드, s.cnt 결제건수,
               (s.amount / s.cnt)::BIGINT 객단가
        FROM sales s JOIN area a USING (area_cd) WHERE s.cnt > 0
        ORDER BY 객단가 DESC LIMIT {n}
    """).fetchdf()


def share_sums(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """비중 칸의 합계가 총매출과 맞는가. 성별·연령은 '미상'이 있어 1보다 작다."""
    ages = " + ".join(f"age_{a}_amount" for a in ("10", "20", "30", "40", "50", "60"))
    times = " + ".join(
        f"time_{t}_amount" for t in ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24")
    )
    rows = []
    for name, expr in [
        ("성별 합", "male_amount + female_amount"),
        ("연령 합", ages),
        ("시간대 합", times),
    ]:
        r = con.execute(f"""
            SELECT quantile_cont(({expr}) / amount, [0.01, 0.5, 0.99]),
                   count(*) FILTER (WHERE ({expr}) > amount * 1.001)
            FROM sales WHERE amount > 0
        """).fetchone()
        rows.append(
            {
                "항목": name,
                "p1": round(r[0][0], 3),
                "중앙": round(r[0][1], 3),
                "p99": round(r[0][2], 3),
                "총매출 초과": r[1],
            }
        )
    return pd.DataFrame(rows)


def read_csv(path: Path) -> pd.DataFrame:
    """서울시 CSV 는 cp949 가 많다. 실패하면 utf-8 계열로 넘어간다."""
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("cp949/utf-8", b"", 0, 1, f"인코딩을 못 찾았습니다: {path}")


def inspect_csv(path: Path) -> dict[str, Any]:
    """새로 받은 CSV 실물 검수. **적재 코드를 짜기 전에 먼저 돌린다.**

    지난번 CSV 검수 때 스키마를 5군데 고쳐야 했다 — 성별·연령 교차가 없다,
    합계가 100%가 아니다 같은 것들이 그때 나왔다.
    """
    df = read_csv(path)
    num = df.select_dtypes("number")
    info = pd.DataFrame(
        {
            "칸": df.columns,
            "형": [str(t) for t in df.dtypes],
            "결측": df.isna().sum().to_numpy(),
            "고유값": df.nunique().to_numpy(),
            "예시": [df[c].dropna().iloc[0] if df[c].notna().any() else None for c in df.columns],
        }
    )
    return {
        "행수": len(df),
        "칸수": len(df.columns),
        "칸별": info,
        "수치 요약": num.describe().T if not num.empty else pd.DataFrame(),
        "전부 0인 칸": [c for c in num.columns if (num[c] == 0).all()],
        "음수가 있는 칸": [c for c in num.columns if (num[c] < 0).any()],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="상권 데이터 검수")
    ap.add_argument("--csv", help="새로 받은 CSV 경로 (glob 가능)")
    ap.add_argument("--db", type=Path, default=DB)
    args = ap.parse_args()

    pd.set_option("display.width", 200, "display.max_columns", 50)

    if args.csv:
        for p in sorted(glob.glob(args.csv)):
            r = inspect_csv(Path(p))
            print(f"\n{'=' * 78}\n{Path(p).name}  —  {r['행수']:,}행 × {r['칸수']}칸\n{'=' * 78}")
            print(r["칸별"].to_string(index=False))
            if r["전부 0인 칸"]:
                print(f"\n⚠️ 전부 0인 칸 (쓸 수 없음): {r['전부 0인 칸']}")
            if r["음수가 있는 칸"]:
                print(f"⚠️ 음수가 있는 칸: {r['음수가 있는 칸']}")
        return 0

    if not args.db.exists():
        print(f"{args.db} 가 없습니다. python etl/load_csv.py 를 먼저 돌리세요.")
        return 1

    con = duckdb.connect(str(args.db), read_only=True)
    keys = {
        "area": "area_cd",
        "sales": "area_cd, category_cd, quarter",
        "foot": "area_cd, quarter",
        "store": "area_cd, category_cd, quarter",
    }
    for title, frame in [
        ("적재 현황", tables(con)),
        ("결측·중복", nulls_and_dupes(con, keys)),
        ("객단가 안정성 (표본 수별)", ticket_stability(con)),
        ("객단가 극단값", ticket_extremes(con)),
        ("비중 합계", share_sums(con)),
    ]:
        print(f"\n── {title} " + "─" * max(0, 60 - len(title)))
        print(frame.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
