"""서울시 상권분석 CSV → DuckDB 적재. 1회 실행.

    python etl/load_csv.py [--src data/raw] [--out data/panel.duckdb]

CSV 4종을 받아 최신 분기만 남기고 4개 테이블로 적재한다.
설계 근거와 데이터 함정은 docs/07_기술계획서_품질검증.md §4.4.

여기서 처리하는 함정:
  · 인코딩이 cp949 다
  · 좌표가 WGS84 가 아니라 EPSG:5181 이다 → 적재 시 1회 변환해 lon/lat 을 함께 저장
  · 성별·연령 매출 합계가 1이 아니다(평균 0.879, 법인카드 등) → 비중은 저장하지 않고
    원본 금액을 그대로 두고 조회 시점에 정규화한다. 여기서 미리 나누면 되돌릴 수 없다.

원본 컬럼을 long 으로 펴지 않고 **wide 그대로** 둔다.
쓰는 쪽이 (상권, 업종) 한 행만 읽으면 되기 때문이다. 펴봐야 행만 20배로 늘고
다시 pivot 해서 쓰게 된다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd
from pyproj import Transformer

#: 상권 좌표계. 지하철역 상권 10곳으로 EPSG:5174 와 비교해 확정했다
#: (5181 평균오차 141m vs 5174 298m). docs/07 §4.4④
AREA_CRS = "EPSG:5181"

AGES = ["10", "20", "30", "40", "50", "60_이상"]
TIMES = ["00~06", "06~11", "11~14", "14~17", "17~21", "21~24"]
FOOT_TIMES = ["00_06", "06_11", "11_14", "14_17", "17_21", "21_24"]

#: 파일명으로 CSV 를 구분한다. 사용자가 받은 파일명을 그대로 쓰기 위한 것.
#: 앞의 4종은 필수, 뒤의 3종은 있으면 적재한다(없으면 해당 피처만 빠진다).
KINDS = {"추정매출": "sales", "길단위인구": "foot", "영역": "area", "점포": "store"}
OPTIONAL_KINDS = {
    "상주인구": "resident",
    "직장인구": "worker",
    "아파트": "apartment",
    "배후지": "back_sales",
}


def read_csv(path: Path) -> pd.DataFrame:
    for enc in ("cp949", "utf-8-sig"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"{path.name}: cp949/utf-8 모두 실패")


def find(src: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for p in src.glob("*.csv"):
        # "추정매출-상권배후지" 는 "추정매출"에도 걸리므로 배후지를 먼저 본다
        for kw, kind in {**OPTIONAL_KINDS, **KINDS}.items():
            if kw in p.name and kind not in found:
                found[kind] = p
    missing = set(KINDS.values()) - set(found)
    if missing:
        raise SystemExit(
            f"{src} 에서 못 찾은 CSV: {sorted(missing)}\n받은 파일: {[p.name for p in src.glob('*.csv')]}"
        )
    return found


def latest(df: pd.DataFrame) -> pd.DataFrame:
    """최신 분기 1개만. 이력은 쓰지 않는다(구성이 5년에 2%p 만 변한다 — §4.4⑥)."""
    q = df["기준_년분기_코드"].max()
    return df[df["기준_년분기_코드"] == q].copy()


def build_area(df: pd.DataFrame) -> pd.DataFrame:
    tr = Transformer.from_crs(AREA_CRS, "EPSG:4326", always_xy=True)
    lon, lat = tr.transform(df["엑스좌표_값"].to_numpy(), df["와이좌표_값"].to_numpy())
    return pd.DataFrame(
        {
            "area_cd": df["상권_코드"].astype(str),
            "area_nm": df["상권_코드_명"],
            "area_type": df["상권_구분_코드_명"],
            "gu_nm": df["자치구_코드_명"],
            "dong_cd": df["행정동_코드"].astype(str),
            "dong_nm": df["행정동_코드_명"],
            "lon": lon,
            "lat": lat,
        }
    )


def build_sales(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "area_cd": df["상권_코드"].astype(str),
            "category_cd": df["서비스_업종_코드"],
            "category_nm": df["서비스_업종_코드_명"],
            "quarter": df["기준_년분기_코드"].astype(str),
            "amount": df["당월_매출_금액"],
            "cnt": df["당월_매출_건수"],
            "weekend_amount": df["주말_매출_금액"],
            "male_amount": df["남성_매출_금액"],
            "female_amount": df["여성_매출_금액"],
        }
    )
    for a in AGES:
        out[f"age_{a.split('_')[0]}_amount"] = df[f"연령대_{a}_매출_금액"]
        # 건수도 같이 싣는다. 금액만으로는 **그 나이대의 객단가**를 못 구한다.
        # 실측(2026Q1): 역삼역 커피-음료 10대 6,420원 vs 60대+ 10,023원(1.6배),
        # 홍대입구역은 10대 12,626원 vs 60대+ 7,833원으로 **방향이 반대**다.
        # 상권 하나에 값 하나만 두면 이 차이가 통째로 사라지고, 손님 12명이
        # 가격에 대해 서로 다르게 판단할 실측 재료가 없어진다.
        out[f"age_{a.split('_')[0]}_cnt"] = df[f"연령대_{a}_매출_건수"]
    for t in TIMES:
        out[f"time_{t.replace('~', '_')}_amount"] = df[f"시간대_{t}_매출_금액"]
    return out


def build_foot(df: pd.DataFrame) -> pd.DataFrame:
    """유동인구. 연령 비중만 쓴다 — '지나다니지만 사지 않는 층'(경계 페르소나) 근거."""
    out = pd.DataFrame(
        {
            "area_cd": df["상권_코드"].astype(str),
            "quarter": df["기준_년분기_코드"].astype(str),
            "total": df["총_유동인구_수"],
        }
    )
    for a in AGES:
        out[f"age_{a.split('_')[0]}_pop"] = df[f"연령대_{a}_유동인구_수"]
    for t in FOOT_TIMES:
        out[f"time_{t}_pop"] = df[f"시간대_{t}_유동인구_수"]
    return out


def build_resident(df: pd.DataFrame) -> pd.DataFrame:
    """상주인구 — 이 상권에 **사는** 사람. 직장인구와 비교해 상권 성격을 가른다.

    성별×연령 교차(`남성연령대_30_상주인구_수`)가 있다. 매출에는 없는 것이라,
    두 축을 곱해 쓰는 우리 가정이 얼마나 어긋나는지 재는 근거로도 쓴다 (§4.4①).
    """
    return pd.DataFrame(
        {
            "area_cd": df["상권_코드"].astype(str),
            "quarter": df["기준_년분기_코드"].astype(str),
            "resident_pop": df["총_상주인구_수"],
            "household_cnt": df["총_가구_수"],
            # 아파트_가구_수 는 최근 8개 분기 내내 0이다(원본이 더 이상 채우지 않는다) → 적재하지 않는다.
        }
    )


def build_worker(df: pd.DataFrame) -> pd.DataFrame:
    """직장인구 — 이 상권으로 **출근하는** 사람."""
    return pd.DataFrame(
        {
            "area_cd": df["상권_코드"].astype(str),
            "quarter": df["기준_년분기_코드"].astype(str),
            "worker_pop": df["총_직장_인구_수"],
        }
    )


def build_apartment(df: pd.DataFrame) -> pd.DataFrame:
    """아파트 — 배후 주거의 가격대. 소득 축의 대리 지표다.

    면적·가격 구간별 세대수는 결측이 많아 쓰지 않고, 결측 없는 평균값만 쓴다.
    """
    return pd.DataFrame(
        {
            "area_cd": df["상권_코드"].astype(str),
            "quarter": df["기준_년분기_코드"].astype(str),
            "apt_cnt": df["아파트_단지_수"],
            "apt_avg_price": df["아파트_평균_시가"],
        }
    )


def build_back_sales(df: pd.DataFrame) -> pd.DataFrame:
    """배후지 매출 — 상권 **주변 생활권**의 매출. 거주 손님에 가깝다.

    같은 (상권, 업종)에서 상권 매출과 연령 구성이 중앙값 10.7%p 벌어진다(§4.4⑩).
    골목상권 1,088곳에만 있고 발달상권·전통시장·관광특구에는 없다.
    """
    out = pd.DataFrame(
        {
            "area_cd": df["상권배후지_코드"].astype(str),
            "category_cd": df["서비스_업종_코드"],
            "quarter": df["기준_년분기_코드"].astype(str),
            "amount": df["당월_매출_금액"],
            "male_amount": df["남성_매출_금액"],
            "female_amount": df["여성_매출_금액"],
        }
    )
    for a in AGES:
        out[f"age_{a.split('_')[0]}_amount"] = df[f"연령대_{a}_매출_금액"]
    return out


def build_store(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "area_cd": df["상권_코드"].astype(str),
            "category_cd": df["서비스_업종_코드"],
            "quarter": df["기준_년분기_코드"].astype(str),
            "store_cnt": df["전체_점포_수"],
            "open_cnt": df["개업_점포_수"],
            "close_cnt": df["폐업_점포_수"],
        }
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=Path("data/panel.duckdb"))
    args = ap.parse_args()

    paths = find(args.src)
    area = build_area(read_csv(paths["area"]))  # 영역엔 분기 컬럼이 없다 (스냅샷 1개)
    sales = build_sales(latest(read_csv(paths["sales"])))
    foot = build_foot(latest(read_csv(paths["foot"])))
    store = build_store(latest(read_csv(paths["store"])))

    tables = [("area", area), ("sales", sales), ("foot", foot), ("store", store)]
    for kind, builder in [
        ("resident", build_resident),
        ("worker", build_worker),
        ("apartment", build_apartment),
        ("back_sales", build_back_sales),
    ]:
        if kind in paths:
            tables.append((kind, builder(latest(read_csv(paths[kind])))))
        else:
            print(f"  (건너뜀) {kind} — CSV 없음. 해당 피처는 비게 된다")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.out))
    for name, df in tables:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df")
        print(f"  {name:6s} {len(df):>7,}행")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS area_pk ON area(area_cd)")
    con.close()

    print(f"\n적재 완료 → {args.out}  (분기 {sales['quarter'].iloc[0]})")
    verify(args.out)


def verify(db: Path) -> None:
    """적재 직후 자가 점검. 조용히 틀린 채로 넘어가는 것을 막는다."""
    con = duckdb.connect(str(db), read_only=True)
    lon_min, lon_max, lat_min, lat_max = con.execute(
        "SELECT min(lon), max(lon), min(lat), max(lat) FROM area"
    ).fetchone()
    orphan = con.execute(
        "SELECT count(*) FROM sales s LEFT JOIN area a USING(area_cd) WHERE a.area_cd IS NULL"
    ).fetchone()[0]
    neg = con.execute("SELECT count(*) FROM sales WHERE amount < 0 OR cnt < 0").fetchone()[0]
    con.close()

    # 서울 대략 범위. 좌표계를 잘못 잡으면 여기서 걸린다.
    assert 126.7 < lon_min and lon_max < 127.3, f"경도 이상: {lon_min}~{lon_max}"
    assert 37.4 < lat_min and lat_max < 37.75, f"위도 이상: {lat_min}~{lat_max}"
    assert orphan == 0, f"area 에 없는 상권코드가 sales 에 {orphan}건"
    assert neg == 0, f"음수 매출 {neg}건"
    print(
        f"자가점검 OK — 경도 {lon_min:.3f}~{lon_max:.3f} / 위도 {lat_min:.3f}~{lat_max:.3f}, 고아행 0"
    )


if __name__ == "__main__":
    sys.exit(main())
