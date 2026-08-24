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

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from api import jobs, session
from app_core import ads, auth, copy_gen, llm, registry, stores
from app_core.panel.aggregate import AggregationError
from app_core.panel.features import NoTradeAreaError, build_features
from app_core.panel.review import CLEAR_MARGIN, rank
from app_core.schema import AdBrief, CopyCandidate, Store, StoreInput

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
    #: 글자 없는 유형은 문구를 안 받는다 — 그래서 여기서 필수가 아니다.
    #: 문구가 필요한 유형인데 비어 있으면 아래 검증이 막는다.
    headline: str = ""
    sub: str = ""
    situation: str = ""
    tone: str = ""
    #: 사장님이 **대화보다 먼저** 고른 결과물 유형 (화면 STEP 1).
    #: 어떤 이미지 기능(1~4번)이 도는지는 이 값이 아니라 사진·레퍼런스·스케치를
    #: 올렸는지가 정한다. 이 값은 **글자를 얹을지**만 정한다.
    output_type: Literal["emotional_no_text", "emotional_text", "poster"] = "emotional_text"
    #: 업종이 other 일 때 사장님이 직접 적은 업종명
    industry_note: str = ""

    @model_validator(mode="after")
    def _copy_needed_when_text(self) -> ImageRequest:
        # 글자가 들어가는 유형인데 문구가 비면 작업 스레드 안에서 터진다.
        # 등록 단계에서 막아야 사장님이 한참 기다린 끝에 오류를 보지 않는다.
        if self.output_type != "emotional_no_text" and not self.headline.strip():
            raise ValueError("글자가 들어가는 결과물은 문구가 있어야 합니다")
        return self

    @model_validator(mode="after")
    def _other_needs_note(self) -> ImageRequest:
        # _render 가 만드는 Store 에 같은 규칙이 있다. 여기서 안 막으면 등록은
        # 통과하고 **작업 스레드 안에서** ValidationError 로 죽어서, 사장님은
        # 한참 기다린 끝에 pydantic 오류 문장을 보게 된다.
        if self.industry == "other" and not self.industry_note.strip():
            raise ValueError("기타를 고르셨으면 업종을 직접 적어주세요")
        return self


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
    #: 이미지 작업이 끝났을 때만. PIL 이미지는 JSON 에 못 실어서 따로 내려준다.
    image_url: str | None = None
    #: 그 밖의 작업(문구·손님 반응)이 끝났을 때 결과를 그대로 싣는다.
    result: Any | None = None


def _render(req: ImageRequest) -> Any:
    """작업 스레드에서 도는 부분. 무거운 import 는 여기서 한다 —
    확산 모델을 안 쓰는 환경에서도 서버는 떠야 한다."""
    from app_core import pipeline

    copy = (
        CopyCandidate(headline=req.headline, sub=req.sub)
        if pipeline.needs_copy(req.output_type)
        else None
    )
    return pipeline.generate_output(
        AdBrief(
            goal="image",
            product=req.product,
            price=req.price,
            situation=req.situation,
            tone=req.tone,
        ),
        Store(
            id=0,
            user_id=0,
            name=req.store_name,
            industry=req.industry,
            industry_note=req.industry_note,
        ),
        req.output_type,
        copy,
    )


@app.post("/ads/image", status_code=202)
def make_image(req: ImageRequest) -> JobAccepted:
    """광고 이미지 만들기를 **등록만** 한다. 진행 상태는 /jobs/{id} 로 물어본다."""
    job = jobs.submit(_render, req, kind="image")
    return JobAccepted(job_id=job.id)


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> JobStatus:
    job = jobs.get(job_id)
    if job is None:
        # 서버를 재시작하면 진행 중이던 작업이 날아간다. 404 를 받으면 화면은
        # 영원히 기다리지 말고 다시 등록해야 한다.
        raise HTTPException(404, "그런 작업이 없습니다. 다시 만들어주세요.")
    done = job.status == "done"
    return JobStatus(
        job_id=job.id,
        status=job.status,
        elapsed_ms=job.elapsed_ms,
        waited_ms=job.waited_ms,
        error=job.error,
        image_url=f"/jobs/{job.id}/image" if done and job.kind == "image" else None,
        result=job.result if done and job.kind == "json" else None,
    )


# ── 로그인 · 내 가게 ────────────────────────────────────────────
# 화면은 로그인하고 받은 토큰을 Authorization 헤더에 담아 보낸다.
# user_id 를 그대로 주고받으면 아무나 남의 번호를 적어 남의 가게를 열 수 있다.


def current_user(authorization: str = Header(default="")) -> int:
    """`Authorization: Bearer <토큰>` 에서 user_id 를 꺼낸다."""
    scheme, _, token = authorization.partition(" ")
    user_id = session.read(token) if scheme.lower() == "bearer" else None
    if user_id is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user_id


class SignupBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    #: 저장은 app_core.auth 가 scrypt 로 해시한다. 여기서 평문을 남기지 않는다.
    password: str = Field(min_length=8, max_length=200)


class LoginBody(BaseModel):
    """로그인은 길이를 검사하지 않는다.

    가입 기준(8자)을 로그인에도 걸면 두 가지가 망가진다 — 기준이 바뀌기 전에
    만든 짧은 비밀번호로는 아예 못 들어오고, 422 와 401 이 갈려서 밖에서
    "이 비밀번호는 길이는 맞았다"를 알 수 있다.
    """

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class Session(BaseModel):
    user_id: int
    token: str


@app.post("/auth/signup", status_code=201)
def signup(body: SignupBody) -> Session:
    try:
        user_id = auth.signup(body.username, body.password)
    except ValueError as exc:
        # 이미 있는 아이디 등 — 사장님이 고칠 수 있는 문제라 그대로 전한다.
        raise HTTPException(409, str(exc)) from exc
    return Session(user_id=user_id, token=session.issue(user_id))


@app.post("/auth/login")
def login(body: LoginBody) -> Session:
    user_id = auth.login(body.username, body.password)
    if user_id is None:
        # 아이디가 없는 건지 비밀번호가 틀린 건지 구분해 말하지 않는다 —
        # 구분해주면 어떤 아이디가 있는지 훑어볼 수 있다.
        raise HTTPException(401, "아이디나 비밀번호가 맞지 않습니다.")
    return Session(user_id=user_id, token=session.issue(user_id))


@app.get("/stores")
def my_stores(user_id: int = Depends(current_user)) -> list[Store]:
    return stores.list_stores(user_id)


@app.post("/stores", status_code=201)
def add_store(body: StoreInput, user_id: int = Depends(current_user)) -> Store:
    return stores.add(user_id, body)


@app.get("/stores/{store_id}")
def one_store(store_id: int, user_id: int = Depends(current_user)) -> Store:
    # stores.get 이 user_id 로 걸러준다 — 남의 가게 번호를 넣으면 None 이 온다.
    return _my_store(user_id, store_id)


# ── 문구 · 손님 반응 ────────────────────────────────────────────
# 둘 다 LLM 을 부른다. 문구는 몇 초, 손님 반응은 1분쯤 걸려서(후보 셋 × 손님 12명)
# 이미지와 같은 등록-폴링 통로를 쓴다. 결과는 JSON 이라 /jobs/{id} 가 그대로 싣는다.


class BriefBody(BaseModel):
    """주문서 — 화면이 대화로 채운 값. AdBrief 의 필수 슬롯만 받는다."""

    store_id: int
    product: str = Field(min_length=1, description="홍보 대상")
    price: int = Field(ge=0, description="원 단위. 0 이면 광고에 가격을 넣지 않는다")
    situation: str = ""
    tone: str = ""
    extra: str = ""


class CopyRequest(BriefBody):
    #: 다시 만들기면 직전 광고를 가리킨다 — 덮어쓰지 않아야 "아까 그게 나았는데"가 된다
    parent_id: int | None = None


class ReviewRequest(BriefBody):
    #: 어떤 광고의 문구를 평가할지. /ads/copies 가 돌려준 값.
    ad_id: int
    #: 좌표를 주면 카카오 지오코딩을 건너뛴다 (/trade-area 와 같은 이유)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


def _brief(body: BriefBody, goal: Literal["copy", "image"]) -> AdBrief:
    return AdBrief(
        goal=goal,
        product=body.product,
        price=body.price,
        situation=body.situation,
        tone=body.tone,
        extra=body.extra,
    )


def _my_store(user_id: int, store_id: int) -> Store:
    store = stores.get(user_id, store_id)
    if store is None:
        raise HTTPException(404, "그런 가게가 없습니다.")
    return store


def _make_copies(store: Store, body: CopyRequest) -> dict[str, Any]:
    """작업 스레드에서 도는 부분."""
    brief = _brief(body, "copy")
    # recent 를 넣는 이유: 이 가게가 최근에 만든 광고를 프롬프트에 넣어야
    # 같은 헤드라인이 또 나오지 않는다 (app.py 와 같은 인자).
    copies = copy_gen.generate(brief, store, ads.recent(store.id))
    if not copies:
        # 빈 목록이 나오는 길은 셋이고 증상이 똑같다 — MODEL_PROFILE 이 stub /
        # LLM 이 candidates 를 빠뜨림 / 후보 전부가 검증 탈락. 조용히 빈 목록을
        # 돌려주면 화면은 "고장인지 느린 건지" 알 수 없다.
        hint = " (MODEL_PROFILE 이 stub 이라 항상 빈 결과입니다)" if llm.profile() == "stub" else ""
        raise ValueError(f"문구를 만들지 못했습니다. 다시 눌러주세요.{hint}")

    ad_id = ads.save(store.id, brief, copies, parent_id=body.parent_id)
    # DB 가 붙인 id 를 실어 다시 꺼낸다 — 화면이 문자열이 아니라 id 로 문구를 짚는다
    return {"ad_id": ad_id, "copies": [c.model_dump() for c in ads.copies_of(store.id, ad_id)]}


def _review(store: Store, body: ReviewRequest) -> dict[str, Any]:
    """작업 스레드에서 도는 부분. 후보 전부를 손님들에게 보여주고 순위를 매긴다."""
    copies = ads.copies_of(store.id, body.ad_id)
    if not copies:
        raise ValueError("평가할 문구가 없습니다. 문구를 먼저 만들어주세요.")

    coord = (body.lon, body.lat) if body.lat is not None and body.lon is not None else None
    try:
        ranked = rank(store, _brief(body, "copy"), copies, ad_id=str(body.ad_id), coord=coord)
    except NoTradeAreaError as exc:
        # 원문에는 "coord 를 직접 넘기세요" 같은 개발자 문장이 섞여 있다.
        # 사장님이 할 수 있는 말만 남기고 원문은 로그로 보낸다.
        raise ValueError("이 주소로는 동네 손님을 불러오지 못했습니다.") from exc
    except AggregationError as exc:
        raise ValueError(f"손님 반응을 모으지 못했습니다. 다시 눌러주세요. ({exc})") from exc

    return {
        # 이 값보다 벌어져야 "1등이 낫다"고 말한다. 화면이 같은 기준으로 문장을
        # 고르도록 서버가 준다 — 양쪽에 숫자를 따로 두면 서로 다르게 늙는다.
        "clear_margin": CLEAR_MARGIN,
        "ranked": [
            {
                "copy": r.copy.model_dump(),
                "result": r.result.model_dump(),
                "defects": [d._asdict() for d in r.defects],
            }
            for r in ranked
        ],
    }


@app.post("/ads/copies", status_code=202)
def make_copies_job(body: CopyRequest, user_id: int = Depends(current_user)) -> JobAccepted:
    """문구 후보 만들기를 **등록만** 한다. 몇 초 걸린다."""
    store = _my_store(user_id, body.store_id)
    return JobAccepted(job_id=jobs.submit(_make_copies, store, body).id, poll_after_ms=1500)


@app.post("/ads/review", status_code=202)
def review_job(body: ReviewRequest, user_id: int = Depends(current_user)) -> JobAccepted:
    """손님 평가를 **등록만** 한다. 후보 셋 × 손님 12명이라 1분쯤 걸린다."""
    store = _my_store(user_id, body.store_id)
    return JobAccepted(job_id=jobs.submit(_review, store, body).id, poll_after_ms=3000)


@app.get("/jobs/{job_id}/image")
def job_image(job_id: str) -> Response:
    """완성된 이미지를 PNG 로 돌려준다."""
    job = jobs.get(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "아직 결과가 없습니다.")
    if job.kind != "image":
        # 문구·평가 작업의 결과는 dict 다. 여기서 막지 않으면 아래에서 dict.save()
        # 를 불러 500 이 난다 — kind 를 붙이기 전에는 모든 작업이 이미지라
        # 안전했던 자리다. (귀한님 #66 리뷰)
        raise HTTPException(404, "이 작업에는 이미지가 없습니다.")
    buf = io.BytesIO()
    job.result.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")
