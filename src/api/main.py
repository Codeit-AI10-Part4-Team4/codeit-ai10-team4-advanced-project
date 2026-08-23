"""FastAPI entrypoint.

라우터는 얇게 — 요청 검증 → app_core 호출 → 응답 변환. 로직은 app_core 에 있다.

지금 붙어 있는 것은 **LLM 키가 없어도 도는 것들**이다. 상권 피처는 서울시 실측을
data/panel.duckdb 에서 읽어오므로 키 없이 진짜 숫자가 나온다. 문구 생성·손님 평가는
모델을 부르므로 여기에 아직 없다 (MODEL_PROFILE=stub 은 빈 결과를 준다).
"""

from __future__ import annotations

import io
import os
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api import jobs
from app_core import registry
from app_core.panel.features import NoTradeAreaError, build_features
from app_core.schema import AdBrief, CopyCandidate, Store

app = FastAPI(title="codeit-ai10-team4-advanced-project")

# 화면은 GitHub Pages(다른 오리진)에서 뜨므로 브라우저가 막는다.
# 열어줄 곳은 환경변수로 받는다 — 코드에 배포 주소를 박으면 옮길 때마다 고쳐야 한다.
_origins = [o.strip() for o in os.getenv("WEB_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


class Industry(BaseModel):
    """가게 등록 화면의 업종 선택지 한 개."""

    id: str
    label: str
    emoji: str = ""


@app.get("/industries")
def industries() -> list[Industry]:
    """업종 선택지. 화면이 목록을 직접 들고 있으면 서버와 갈라진다."""
    return [Industry(**i) for i in registry.industry_options()]


class TradeArea(BaseModel):
    """결과 화면의 '동네 숫자와 견줘보면' 절이 쓰는 값만 추린 것.

    `build_features` 는 30개 넘는 키를 돌려주는데 비중 딕셔너리까지 그대로
    내려보내면 화면이 서버 내부 모양에 묶인다. 화면이 실제로 읽는 것만 담는다.
    """

    area_nm: str
    area_type: str
    #: "20261" = 2026년 1분기. 표시 변환은 화면이 한다.
    quarter: str
    category_nm: str
    #: 주소로 동네를 못 찾아 서울 평균을 썼는가
    is_fallback: bool
    #: 같은 업종 데이터가 적어 동네 전체 평균을 썼는가 — 객단가가 통째로 달라진다
    is_category_fallback: bool
    #: 객단가(원) = 당월_매출_금액 / 당월_매출_건수
    avg_ticket: int
    #: 서울 동일 업종 내 분위(0~1)
    avg_ticket_pct: float
    #: 매출이 가장 많은 시간대와 그 비중 — "점심(11-14시)에 42%" 문장의 근거
    peak_time: str
    peak_share: float
    weekend_ratio: float
    competitor_cnt: int
    open_cnt: int
    close_cnt: int


_PASS_THROUGH = (
    "area_nm",
    "area_type",
    "quarter",
    "category_nm",
    "is_category_fallback",
    "avg_ticket",
    "avg_ticket_pct",
    "weekend_ratio",
    "competitor_cnt",
    "open_cnt",
    "close_cnt",
)


def _to_trade_area(features: dict[str, Any]) -> TradeArea:
    peak, share = max(features["time_share"].items(), key=lambda kv: kv[1])
    return TradeArea(
        peak_time=peak,
        peak_share=round(share, 4),
        # ⚠️ build_features 는 is_fallback 을 아예 넣지 않는다. 스키마의 기본값(False)만
        #    존재하고 True 로 만드는 운영 코드가 한 줄도 없다 — app.py 의
        #    "서울 평균으로 평가했습니다" 경고는 그래서 뜰 수 없다.
        #    주소를 못 찾으면 폴백이 아니라 NoTradeAreaError 로 끝나기 때문이다.
        #    여기서는 없는 키로 죽지 않게 기본값을 쓰고, 처리 방향은 팀에 올린다.
        is_fallback=bool(features.get("is_fallback", False)),
        **{k: features[k] for k in _PASS_THROUGH},
    )


@app.get("/trade-area")
def trade_area(
    address: str = Query(min_length=1, description="가게 주소 (지번·도로명 모두 가능)"),
    industry: str = Query(min_length=1, description="업종 id — /industries 의 값"),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
) -> TradeArea:
    """주소·업종 → 그 동네의 서울시 실측.

    `lat`/`lon` 을 같이 주면 지오코딩을 건너뛴다. KAKAO_REST_KEY 없이 쓰는 통로다.
    """
    if (lat is None) != (lon is None):
        raise HTTPException(400, "lat 과 lon 은 같이 주거나 같이 빼세요.")
    coord = (lon, lat) if lat is not None and lon is not None else None
    try:
        features = build_features(address, industry, coord=coord)
    except NoTradeAreaError as exc:
        # 원문에는 "coord 를 직접 넘기세요" 같은 개발자 문장이 섞여 있다.
        # 사장님 화면에 그대로 뜨지 않도록 상태 코드로 구분하고 원문은 detail 에 남긴다.
        raise HTTPException(404, str(exc)) from exc
    return _to_trade_area(features)


# ── 오래 걸리는 작업 ────────────────────────────────────────────
# 이미지 한 장이 GPU 없는 기계에서 18초다. 응답을 붙들고 있으면 브라우저는 멈춘
# 것처럼 보이고 게이트웨이는 끊는다 — 번호를 주고 물어보게 한다.


class ImageRequest(BaseModel):
    """광고 이미지 한 장을 만드는 데 필요한 최소한."""

    store_name: str = Field(min_length=1)
    industry: str = Field(min_length=1)
    product: str = Field(min_length=1)
    #: 원 단위 정수. 화면의 "8,000원"은 보낼 때 숫자로 바꾼다 —
    #: 쉼표·단위를 서버가 풀기 시작하면 "팔천원"까지 받아줘야 한다.
    price: int = Field(ge=0)
    headline: str = Field(min_length=1)
    sub: str = ""
    situation: str = ""
    tone: str = ""
    style: Literal["simple", "poster"] = "simple"


class JobAccepted(BaseModel):
    job_id: str
    #: 화면이 얼마나 자주 물어볼지 정하는 데 쓴다
    poll_after_ms: int = 2000


class JobStatus(BaseModel):
    job_id: str
    status: jobs.Status
    #: 실제로 도는 데 걸린 시간 (줄 선 시간 제외)
    elapsed_ms: int
    #: 등록하고부터 흐른 시간 — 화면이 사장님께 보여주는 숫자
    waited_ms: int = 0
    #: 실패했을 때만 채워진다
    error: str | None = None
    #: 끝났으면 결과를 어디서 가져가는지
    image_url: str | None = None


def _render(req: ImageRequest) -> Any:
    """작업 스레드에서 도는 부분. 무거운 import 는 여기서 한다 —
    확산 모델을 안 쓰는 환경에서도 서버는 떠야 한다."""
    from app_core import pipeline

    return pipeline.generate_ad(
        AdBrief(
            goal="image",
            product=req.product,
            price=req.price,
            situation=req.situation,
            tone=req.tone,
        ),
        Store(id=0, user_id=0, name=req.store_name, industry=req.industry),
        CopyCandidate(headline=req.headline, sub=req.sub),
        style=req.style,
    )


@app.post("/ads/image", status_code=202)
def make_image(req: ImageRequest) -> JobAccepted:
    """광고 이미지 만들기를 **등록만** 한다. 진행 상태는 /jobs/{id} 로 물어본다."""
    job = jobs.submit(_render, req)
    return JobAccepted(job_id=job.id)


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> JobStatus:
    job = jobs.get(job_id)
    if job is None:
        # 서버를 재시작하면 진행 중이던 작업이 날아간다. 404 를 받으면 화면은
        # 영원히 기다리지 말고 다시 등록해야 한다.
        raise HTTPException(404, "그런 작업이 없습니다. 다시 만들어주세요.")
    return JobStatus(
        job_id=job.id,
        status=job.status,
        elapsed_ms=job.elapsed_ms,
        waited_ms=job.waited_ms,
        error=job.error,
        image_url=f"/jobs/{job.id}/image" if job.status == "done" else None,
    )


@app.get("/jobs/{job_id}/image")
def job_image(job_id: str) -> Response:
    """완성된 이미지를 PNG 로 돌려준다."""
    job = jobs.get(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "아직 결과가 없습니다.")
    buf = io.BytesIO()
    job.result.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")
