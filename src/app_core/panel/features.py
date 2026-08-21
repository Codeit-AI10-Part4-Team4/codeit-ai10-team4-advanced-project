"""주소 + 업종 → 상권 피처.

패널 구성의 입력을 만든다. **전 필드가 결정적으로 계산된다 — LLM 이 개입하지 않는다.**
설계 근거는 docs/07_기술계획서_품질검증.md §4.

여기서 하는 일은 넷이다.
  1. 주소 → 좌표          (카카오 로컬 API. 키가 없으면 좌표를 직접 넘길 수 있다)
  2. 좌표 → 최근접 상권    (적재 시 변환해둔 lon/lat 으로 거리 비교)
  3. 업종 → 서울시 업종코드 (여러 개를 합쳐 읽는다 — §4.5)
  4. 비중 계산            (성별·연령 합계가 1이 아니라 여기서 정규화한다)

원본 금액을 나눠 비중을 만드는 곳은 여기 한 곳뿐이다. ETL 은 금액을 그대로 둔다.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final

import duckdb


def _one(cur: duckdb.DuckDBPyConnection) -> tuple[Any, ...]:
    """집계 쿼리는 항상 한 행을 돌려준다. None 은 SQL 이 잘못된 경우뿐이다."""
    row = cur.fetchone()
    if row is None:  # pragma: no cover - 방어
        raise NoTradeAreaError("조회 결과가 비었습니다.")
    return row


DB_PATH: Final = Path(os.getenv("PANEL_DB", "data/panel.duckdb"))

AGE_BANDS: Final = ("10", "20", "30", "40", "50", "60")
TIME_BANDS: Final = ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24")

#: industries.yaml 의 id → 서울시 서비스업종코드. 여러 개면 금액을 합쳐 읽는다.
#: 서울시 분류가 우리 업종보다 잘게 쪼개져 있어 하나만 보면 커버리지가 낮게 나온다
#: (fitness 17% → 42%). 근거·커버리지 표는 docs/07 §4.5.
#: 값이 빈 튜플이면 업종 축 없이 상권 전체로 폴백한다.
CATEGORY_MAP: Final[dict[str, tuple[str, ...]]] = {
    # 음식
    "korean_food": ("CS100001",),
    "grill": ("CS100001",),  # 고기·구이는 서울시에 별도 코드가 없다 → 한식
    "chinese_food": ("CS100002",),
    "japanese_food": ("CS100003",),
    "western_food": ("CS100004",),  # industries.yaml 에 추가 건의됨 (§4.5)
    "bakery": ("CS100005",),
    "pizza_burger": ("CS100006",),
    "chicken": ("CS100007",),
    "snack": ("CS100008",),
    "pub": ("CS100009",),
    "cafe": ("CS100010",),
    # 소매
    "grocery": ("CS300001",),
    "convenience": ("CS300002",),
    "butcher": ("CS300007",),
    "produce": ("CS300009",),
    "sidedish": ("CS300010",),
    "clothing": ("CS300011",),
    "optician": ("CS300016",),
    "pharmacy": ("CS300018",),
    "cosmetics": ("CS300022",),
    "flower": ("CS300028",),
    "petshop": ("CS300029",),
    # 서비스
    "academy": ("CS200001", "CS200002", "CS200003"),  # 일반교습+외국어+예술
    "fitness": ("CS200024", "CS200005", "CS200017", "CS200016"),  # 스포츠클럽+강습+골프+당구
    "carrepair": ("CS200025",),
    "salon": ("CS200028",),
    "nail": ("CS200029",),
    "skincare": ("CS200030",),
    "laundry": ("CS200031",),
    "realestate": ("CS200033",),
    # 상권 데이터에 대응 업종이 없다 → 상권 전체 평균으로 폴백
    "photostudio": (),
    "other": (),
}


class NoTradeAreaError(Exception):
    """주소를 상권에 붙이지 못했다. 사장님 언어로 안내해야 한다."""


def geocode(address: str) -> tuple[float, float]:
    """주소 → (경도, 위도). 카카오 로컬 API.

    `KAKAO_REST_KEY` 가 없으면 쓸 수 없다. 키 없이 개발할 때는
    `build_features(..., coord=(lon, lat))` 로 좌표를 직접 넘긴다.
    """
    key = os.getenv("KAKAO_REST_KEY")
    if not key:
        raise NoTradeAreaError("KAKAO_REST_KEY 가 없습니다. coord 를 직접 넘기세요.")
    url = "https://dapi.kakao.com/v2/local/search/address.json?" + urllib.parse.urlencode(
        {"query": address}
    )
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {key}"})
    with urllib.request.urlopen(req, timeout=10) as res:
        docs = json.load(res).get("documents", [])
    if not docs:
        raise NoTradeAreaError(f"주소를 찾지 못했습니다: {address}")
    return float(docs[0]["x"]), float(docs[0]["y"])


# 서울 밖 주소를 "가장 가까운 상권"으로 억지로 붙이지 않기 위한 상한.
# 실측: 상권끼리 최근접 간격 p99 837m / 최대 1,801m. 서울 변두리 실주소 8건에서
# 가장 먼 경우가 도봉동 산자락 2,349m. 부산 해운대는 313km 였다. 사이가 넓다.
MAX_MATCH_M = 3_000.0


def _haversine_sql() -> str:
    """DuckDB 안에서 거리(m)를 재는 식. 상권 1,650개라 전수 비교로 충분하다."""
    return (
        "6371000 * 2 * asin(sqrt("
        "  pow(sin(radians(lat - ?) / 2), 2)"
        "  + cos(radians(?)) * cos(radians(lat)) * pow(sin(radians(lon - ?) / 2), 2)"
        "))"
    )


def match_area(con: duckdb.DuckDBPyConnection, lon: float, lat: float) -> dict[str, Any]:
    """좌표에서 가장 가까운 상권. 거리도 함께 준다(신뢰도 판단에 쓴다).

    **매출 데이터가 있는 상권만 후보로 둔다.** 상권 1,650곳 중 86곳(5.2%)은
    `sales` 에 행이 하나도 없다. 그런 곳이 가장 가까우면 `_sales_row` 가
    "이 상권에는 매출 데이터가 없습니다" 로 죽어 **주소가 통째로 못 쓰게 된다**
    — 실주소 17곳으로 재보니 1곳이 여기 걸렸다 (2026-08-21).

        서울 마포구 백범로 152 (공덕파크자이)
          염리초등학교        202m   매출   0건  ← 여기로 붙어서 실패
          공덕역(공덕오거리)   394m   매출  26건  ← 192m 더 가면 있다

    빈 상권 86곳 전부, 가장 가까운 "데이터 있는 상권"이 중앙값 285m ·
    최대 1,129m 로 `MAX_MATCH_M` 안에 있다. 즉 이 필터로 86곳이 전부
    구제되고, 서울 밖 주소를 막는 거리 상한은 그대로 살아 있다.

    빈 상권 이름은 청운초등학교·세화어린이공원·마장지하차도처럼 **주거지·생활
    시설**이 많다. 동네 가게 사장님이 정확히 그런 곳에 있다.
    """
    row = _one(
        con.execute(
            f"SELECT area_cd, area_nm, area_type, gu_nm, dong_nm, {_haversine_sql()} AS dist "
            "FROM area WHERE area_cd IN (SELECT area_cd FROM sales) "
            "ORDER BY dist LIMIT 1",
            [lat, lat, lon],
        )
    )
    if row[5] > MAX_MATCH_M:
        raise NoTradeAreaError(
            "서울 안의 주소가 아닌 것 같습니다. "
            f"가장 가까운 상권({row[1]})이 {row[5] / 1000:.0f}km 떨어져 있습니다. "
            "지금은 서울시 상권 데이터만 갖고 있어 다른 지역은 분석할 수 없습니다."
        )
    return {
        "area_cd": row[0],
        "area_nm": row[1],
        "area_type": row[2],
        "gu_nm": row[3],
        "dong_nm": row[4],
        "match_distance_m": round(row[5], 1),
    }


def _shares(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0:
        return {k: 0.0 for k in values}
    return {k: round(v / total, 4) for k, v in values.items()}


#: 업종 매출을 그대로 믿기 위한 최소 분기 결제 건수.
#:
#: 실측 — 같은 업종의 중앙 객단가 대비 상대 편차:
#:     30건 미만   중앙 0.709 / p90 8.96배   ← 자릿수가 틀린다
#:     30~99      중앙 0.558 / p90 5.29배
#:     100~299    중앙 0.424 / p90 2.94배
#:     300~999    중앙 0.362 / p90 1.97배   ← 여기서 p90 이 2 아래로
#:     5천 이상    중앙 0.242 / p90 0.84배   ← 노이즈 바닥(동네별 실제 차이)
#:
#: 결제 6건으로 낸 평균을 "이 동네 평균"이라고 사장님께 말할 수는 없다.
#: 버리지 않고 상권 전체로 폴백한다 — 폴백하면 표본이 중앙값 3,498배 늘고,
#: 화면에는 이미 "이 동네 전체 손님 기준" 배지가 뜬다.
MIN_SALES_CNT: Final = 300


def _sales_row(
    con: duckdb.DuckDBPyConnection, area_cd: str, codes: tuple[str, ...]
) -> tuple[Any, bool]:
    """업종 매출 합계. 그 상권에 업종이 없거나 **표본이 너무 적으면** 전체로 폴백한다.

    커버리지가 낮은 업종(부동산중개는 상권의 1%)에서 에러를 내는 대신,
    업종 축만 빼고 '이 동네 전체 손님'으로 평가를 이어간다 (§4.5).
    """
    cols = (
        "sum(amount) amount, sum(cnt) cnt, sum(weekend_amount) weekend, "
        "sum(male_amount) m, sum(female_amount) f, "
        + ", ".join(f"sum(age_{a}_amount) age_{a}" for a in AGE_BANDS)
        + ", "
        + ", ".join(f"sum(time_{t}_amount) time_{t}" for t in TIME_BANDS)
        + ", "
        # 나이대별 건수. 금액과 나누면 그 나이대의 객단가가 나온다 (`_age_tickets`).
        + ", ".join(f"sum(age_{a}_cnt) agec_{a}" for a in AGE_BANDS)
    )
    if codes:
        ph = ", ".join("?" * len(codes))
        row = con.execute(
            f"SELECT {cols} FROM sales WHERE area_cd = ? AND category_cd IN ({ph})",
            [area_cd, *codes],
        ).fetchone()
        if row and row[0] and row[1] >= MIN_SALES_CNT:
            return row, False
    row = con.execute(f"SELECT {cols} FROM sales WHERE area_cd = ?", [area_cd]).fetchone()
    if not row or not row[0]:
        raise NoTradeAreaError("이 상권에는 매출 데이터가 없습니다.")
    return row, True


def _back_shares(
    con: duckdb.DuckDBPyConnection, area_cd: str, codes: tuple[str, ...]
) -> dict[str, float] | None:
    """배후지 매출의 연령 비중. 배후지가 없는 상권(발달·전통시장·관광특구)이면 None."""
    where, params = "", [area_cd]
    if codes:
        where = f" AND category_cd IN ({', '.join('?' * len(codes))})"
        params += list(codes)
    row = con.execute(
        "SELECT "
        + ", ".join(f"sum(age_{a}_amount)" for a in AGE_BANDS)
        + f" FROM back_sales WHERE area_cd = ?{where}",
        params,
    ).fetchone()
    if not row or not any(row) or sum(x or 0 for x in row) <= 0:
        return None
    return _shares(dict(zip(AGE_BANDS, [x or 0 for x in row], strict=True)))


def _ticket_percentile(
    con: duckdb.DuckDBPyConnection, codes: tuple[str, ...], ticket: int
) -> float:
    """서울 전체에서 이 상권 객단가가 몇 분위인가. price_sens 판정의 근거."""
    where = ""
    params: list[Any] = []
    if codes:
        where = f"AND category_cd IN ({', '.join('?' * len(codes))})"
        params = list(codes)
    rows = con.execute(
        f"SELECT sum(amount) / sum(cnt) FROM sales WHERE cnt > 0 {where} GROUP BY area_cd", params
    ).fetchall()
    tickets = [r[0] for r in rows if r[0]]
    if not tickets:
        return 0.5
    return round(sum(t < ticket for t in tickets) / len(tickets), 3)


def _age_tickets(
    amounts: dict[str, Any], cnts: dict[str, Any]
) -> tuple[dict[str, int | None], int]:
    """나이대별 객단가와 그 기준값.

    **손님 12명이 가격을 서로 다르게 판단할 수 있는 유일한 실측 재료다.**
    상권 객단가 하나만 쓰면 12명이 같은 숫자와 견주게 되어 답이 하나로 모인다.

    실측(2026Q1) — 같은 업종인데 상권마다 **방향이 반대**다.

        역삼역 커피-음료    10대  6,420원  →  60대+ 10,023원   (나이 들수록 오름)
        홍대입구역 커피-음료 10대 12,626원  →  60대+  7,833원   (나이 들수록 내림)

    건수가 적은 칸은 `None` 이다. 기준은 `MIN_SALES_CNT` 를 그대로 쓴다 —
    상권 단위에서 쓰던 것과 같은 노이즈 문제이고 근거표도 같기 때문이다.
    실제로 이 선 아래에서 값이 튄다: 역삼 치킨 10대는 **14건**으로 92,005원
    (그 업종 전체 60,228원의 1.5배), 도봉산 한식 10대는 **83건**으로 72,209원(1.9배).

    ⚠️ 객단가는 **결제 1건**의 평균이라 여러 개를 산 경우가 섞여 있다. 그래서 이 값은
    "그 나이대가 이 동네에서 한 번에 쓰는 돈"이지 품목 가격이 아니다. 상권 단위
    `avg_ticket` 과 같은 성질이라 새로 생긴 한계는 아니다.

    Returns:
        (나이대별 객단가, 기준 객단가). 기준은 **믿을 만한 칸만** 합쳐 나눈 값이라
        미상 매출이 섞인 `avg_ticket` 과 다르다 — 나이대끼리 견주려면 이쪽이 맞다.
    """
    out: dict[str, int | None] = {}
    for a in AGE_BANDS:
        amt, cnt = amounts.get(a) or 0, cnts.get(a) or 0
        out[a] = int(amt // cnt) if cnt >= MIN_SALES_CNT and amt > 0 else None
    ok = [a for a in AGE_BANDS if out[a] is not None]
    amt_sum = sum(amounts[a] or 0 for a in ok)
    cnt_sum = sum(cnts[a] or 0 for a in ok)
    return out, int(amt_sum // cnt_sum) if cnt_sum else 0


def build_features(
    address: str,
    industry: str,
    *,
    coord: tuple[float, float] | None = None,
    db: Path | None = None,
) -> dict[str, Any]:
    """가게 주소·업종 → 상권 피처. 페르소나 구성(F2)의 입력.

    coord 를 주면 지오코딩을 건너뛴다 (카카오 키 없이 개발·테스트할 때).
    """
    lon, lat = coord if coord else geocode(address)
    if db is None and not DB_PATH.exists():
        # data/ 는 gitignore 라 클론만 한 팀원에게는 파일이 없다. 막지 않으면
        # duckdb 의 IOException 이 전체 경로와 함께 화면에 그대로 뜬다.
        raise NoTradeAreaError(
            f"상권 데이터 파일이 없습니다 ({DB_PATH}). "
            "서울 열린데이터광장 CSV 를 data/raw/ 에 넣고 "
            "`python etl/load_csv.py` 를 한 번 실행해주세요."
        )
    con = duckdb.connect(str(db or DB_PATH), read_only=True)
    try:
        area = match_area(con, lon, lat)
        codes = CATEGORY_MAP.get(industry, ())
        row, fallback = _sales_row(con, area["area_cd"], codes)

        amount, cnt, weekend, male, female = row[0], row[1], row[2], row[3], row[4]
        na, nt = len(AGE_BANDS), len(TIME_BANDS)
        ages = dict(zip(AGE_BANDS, row[5 : 5 + na], strict=True))
        times = dict(zip(TIME_BANDS, row[5 + na : 5 + na + nt], strict=True))
        age_cnts = dict(zip(AGE_BANDS, row[5 + na + nt :], strict=True))
        ticket = int(amount // cnt) if cnt else 0
        age_ticket, age_ticket_base = _age_tickets(ages, age_cnts)

        foot = con.execute(
            "SELECT "
            + ", ".join(f"age_{a}_pop" for a in AGE_BANDS)
            + " FROM foot WHERE area_cd = ?",
            [area["area_cd"]],
        ).fetchone()

        # 개업·폐업도 같이 읽는다. 점포 수만으로는 "경쟁이 많다"까지만 알 수 있는데,
        # 사장님에게 필요한 건 그게 늘어나는 중인지 빠지는 중인지다.
        # 실측(2026Q1 서울): 카페 개업 738 / 폐업 853, 한식 1,643 / 1,788.
        store_cnt, open_cnt, close_cnt = _one(
            con.execute(
                "SELECT coalesce(sum(store_cnt), 0), coalesce(sum(open_cnt), 0), "
                "coalesce(sum(close_cnt), 0) FROM store WHERE area_cd = ?"
                + (
                    f" AND category_cd IN ({', '.join('?' * len(codes))})"
                    if codes and not fallback
                    else ""
                ),
                [area["area_cd"], *(codes if codes and not fallback else [])],
            )
        )

        # 상권 성격 — 출퇴근지인가 주거지인가. 시간대 매출로 추론하던 것을 실측으로 대체한다.
        ctx = con.execute(
            "SELECT coalesce(w.worker_pop, 0), coalesce(r.resident_pop, 0), "
            "       coalesce(r.household_cnt, 0), a.apt_avg_price, coalesce(a.apt_cnt, 0) "
            "FROM area ar "
            "LEFT JOIN worker w USING(area_cd) LEFT JOIN resident r USING(area_cd) "
            "LEFT JOIN apartment a USING(area_cd) WHERE ar.area_cd = ?",
            [area["area_cd"]],
        ).fetchone()
        worker_pop, resident_pop, hh, apt_price, apt_cnt = ctx if ctx else (0, 0, 0, None, 0)

        # 배후지 = 상권 주변 생활권. 상권 매출이 '지나가는 손님'이면 이쪽은 '동네 주민'에
        # 가깝고, 실제로 연령 구성이 중앙값 10.7%p 벌어진다(§4.4⑩).
        # 골목상권에만 있어 없으면 None 이 되고, 그 경우 관련 판단은 건너뛴다.
        back_age = _back_shares(con, area["area_cd"], codes)

        quarter = _one(con.execute("SELECT max(quarter) FROM sales"))[0]
        # 어떤 데이터로 만든 피처인지 남긴다. 업종 축이 빠진 폴백이면 그렇게 표기한다.
        # (사장님에게 보여줄 업종명은 store.industry_label 을 쓴다 — 여기 값이 아니다)
        category_nm = (
            "전체 업종"
            if fallback
            else " + ".join(
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT category_nm FROM sales "
                    f"WHERE category_cd IN ({', '.join('?' * len(codes))}) ORDER BY category_nm",
                    list(codes),
                ).fetchall()
            )
        )
        return {
            **area,
            "quarter": quarter,
            "category_cds": [] if fallback else list(codes),
            "category_nm": category_nm,
            "is_category_fallback": fallback,
            # 성별·연령 합계가 1이 아니다(미상 매출). 정규화하고 원래 합계를 남긴다.
            "demo_coverage": round((male + female) / amount, 3) if amount else 0.0,
            "gender_share": _shares({"M": male, "F": female}),
            "age_share": _shares(ages),
            # 시간대는 유동인구가 아니라 매출 기준 — 지나다니는 사람과 사는 사람이 다르다.
            "time_share": _shares({k.replace("_", "-"): v for k, v in times.items()}),
            "foot_age_share": _shares(dict(zip(AGE_BANDS, foot, strict=True))) if foot else {},
            # 동네 주민 쪽 연령 구성. 골목상권에만 있다(전체의 66%).
            "back_age_share": back_age,
            "weekend_ratio": round(weekend / amount, 3) if amount else 0.0,
            "avg_ticket": ticket,
            "avg_ticket_pct": _ticket_percentile(con, () if fallback else codes, ticket),
            # 나이대별 객단가 — 손님 12명이 가격을 다르게 판단하는 근거 (`_age_tickets`).
            # ⚠️ `TradeAreaFeatures`(수호님 소유)가 extra="ignore" 라 이 두 키는 평가
            # 프롬프트까지 못 간다. 지금은 `panel_builder.price_sens` 가 여기서 읽어
            # **페르소나별 축 값**으로 바꿔 넘긴다 — 그 축은 이미 스키마에 있다.
            "age_ticket": age_ticket,
            "age_ticket_base": age_ticket_base,
            "competitor_cnt": int(store_cnt),
            "open_cnt": int(open_cnt),
            "close_cnt": int(close_cnt),
            # 상권 성격: 1에 가까우면 출퇴근 상권, 0에 가까우면 주거 상권
            "worker_pop": int(worker_pop),
            "resident_pop": int(resident_pop),
            "work_ratio": (
                round(worker_pop / (worker_pop + resident_pop), 3)
                if worker_pop + resident_pop
                else None
            ),
            "household_cnt": int(hh),
            # 배후 주거의 가격대 — 소득 축의 대리 지표 (객단가 하나로만 보던 것을 보강).
            # 상권 영역 안에 아파트가 없으면 None (상업지역은 대부분 그렇다).
            "apt_cnt": int(apt_cnt),
            "apt_avg_price": int(apt_price) if apt_price else None,
        }
    finally:
        con.close()
