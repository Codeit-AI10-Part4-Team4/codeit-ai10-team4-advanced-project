"""설치·CI 사슬이 도는지 확인하는 스모크 테스트.

외부 API 는 부르지 않는다 (AGENTS.md). 상권 조회는 좌표를 직접 넘겨
카카오 지오코딩을 건너뛰고, 데이터는 저장소에 있는 data/panel.duckdb 를 읽는다.
"""

import time
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from api import jobs
from api.main import app

client = TestClient(app)

#: 망원동 근처. 좌표를 주면 KAKAO_REST_KEY 없이 돈다.
MANGWON = {
    "address": "서울시 마포구 망원동 123-4",
    "industry": "korean_food",
    "lat": 37.5561,
    "lon": 126.9018,
}

#: 상권 데이터가 없는 환경에서는 상권 테스트를 건너뛴다.
has_db = pytest.mark.skipif(
    not Path("data/panel.duckdb").exists(), reason="data/panel.duckdb 가 없다"
)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_업종_목록은_id_label_emoji_만_준다() -> None:
    """프롬프트용 필드까지 내려보내면 그게 바뀔 때마다 화면이 같이 흔들린다."""
    response = client.get("/industries")
    assert response.status_code == 200
    body = response.json()
    assert len(body) > 10
    assert set(body[0]) == {"id", "label", "emoji"}
    assert any(i["id"] == "korean_food" for i in body)


@has_db
def test_상권은_키_없이_실측을_돌려준다() -> None:
    """좌표를 주면 외부 호출이 하나도 없다. 값은 서울시 원본에서 온다.

    숫자를 못 박지 않고 형식·범위만 본다 — 분기가 바뀌면 값도 바뀐다.
    """
    response = client.get("/trade-area", params=MANGWON)
    assert response.status_code == 200
    body = response.json()
    assert body["quarter"].isdigit() and len(body["quarter"]) == 5  # YYYYQ
    assert body["avg_ticket"] > 0
    assert 0 <= body["peak_share"] <= 1
    assert body["peak_time"]


@has_db
def test_좌표는_둘_다_주거나_둘_다_빼야_한다() -> None:
    """하나만 주면 나머지를 지오코딩해야 하는데, 키가 없으면 거기서 죽는다.
    무엇이 잘못됐는지 입구에서 말해준다."""
    params = {k: v for k, v in MANGWON.items() if k != "lon"}
    assert client.get("/trade-area", params=params).status_code == 400


def test_주소가_비면_거절한다() -> None:
    response = client.get("/trade-area", params={"address": "", "industry": "cafe"})
    assert response.status_code == 422


# ── 오래 걸리는 작업 ────────────────────────────────────────────
# 확산 모델은 부르지 않는다 (한 장에 18초). 폴링 계약만 본다.


#: 아직 끝나지 않은 상태. 한 번에 하나씩 돌리므로(MAX_WORKERS=1) 줄을 서는
#: 시간이 있고, queued 를 끝난 것으로 읽으면 앞 작업이 도는 동안 그냥 통과한다.
_BUSY = {"queued", "running"}


def _wait(job_id: str, timeout: float = 3.0) -> dict[str, Any]:
    """끝날 때까지 물어본다 — 화면이 하는 일과 같다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body: dict[str, Any] = client.get(f"/jobs/{job_id}").json()
        if body["status"] not in _BUSY:
            return body
        time.sleep(0.02)
    raise AssertionError(f"{timeout}초 안에 안 끝났다")


def test_등록하면_바로_번호를_주고_나중에_끝난다() -> None:
    """느린 작업이라도 등록은 즉시 끝나야 한다. 그게 이 구조의 이유다."""
    jobs.clear()

    def 느리다() -> str:
        time.sleep(0.05)
        return "다 됐다"

    job = jobs.submit(느리다)
    assert client.get(f"/jobs/{job.id}").json()["status"] in {"queued", "running", "done"}
    assert _wait(job.id)["status"] == "done"


def test_작업이_터져도_서버는_살아있고_이유를_말한다() -> None:
    """스레드에서 삼키지 않으면 화면은 영원히 running 을 본다."""
    jobs.clear()

    def 터진다() -> None:
        raise ValueError("모델을 못 찾았습니다")

    body = _wait(jobs.submit(터진다).id)
    assert body["status"] == "failed"
    assert body["error"] is not None and "모델을 못 찾았습니다" in body["error"]
    assert body["image_url"] is None


def test_없는_번호는_404() -> None:
    """서버를 재시작하면 진행 중이던 작업이 날아간다. 화면이 영원히
    기다리지 않도록 없다고 말해준다."""
    assert client.get("/jobs/그런건없다").status_code == 404
    assert client.get("/jobs/그런건없다/image").status_code == 404


def test_끝나기_전에는_이미지를_안_준다() -> None:
    jobs.clear()

    def 아직() -> None:
        time.sleep(0.3)

    job = jobs.submit(아직)
    assert client.get(f"/jobs/{job.id}/image").status_code == 404


def test_이미지_요청은_필수값이_빠지면_거절한다() -> None:
    """등록 단계에서 걸러야 한다 — 18초 뒤에 "product 가 없다"고 하면 늦다."""
    assert client.post("/ads/image", json={"store_name": "가게"}).status_code == 422


def test_기타_업종은_직접_적은_이름_없이는_등록도_안_된다() -> None:
    """Store 가 같은 규칙을 갖고 있어서, 여기서 안 막으면 작업 스레드 안에서
    ValidationError 로 죽는다 — 사장님은 한참 기다린 끝에 그걸 본다."""
    body = {
        "store_name": "엄마손 반찬",
        "industry": "other",
        "product": "모둠 반찬",
        "price": 8000,
        "headline": "오늘 반찬 다 됐습니다",
        "output_type": "emotional_text",
    }
    assert client.post("/ads/image", json=body).status_code == 422
    assert client.post("/ads/image", json={**body, "industry_note": "반찬가게"}).status_code == 202


def test_글자_없는_유형은_문구_없이도_등록된다() -> None:
    """글자를 안 얹는 결과물은 문구를 받지 않는다 — 여기서 막으면 영영 못 만든다."""
    body = {
        "store_name": "연남 크로플",
        "industry": "cafe",
        "product": "크로플",
        "price": 4500,
        "output_type": "emotional_no_text",
    }
    assert client.post("/ads/image", json=body).status_code == 202


def test_글자_있는_유형은_문구가_없으면_거절한다() -> None:
    body = {
        "store_name": "연남 크로플",
        "industry": "cafe",
        "product": "크로플",
        "price": 4500,
        "output_type": "poster",
    }
    assert client.post("/ads/image", json=body).status_code == 422
    assert client.post("/ads/image", json={**body, "headline": "겨울 크로플"}).status_code == 202


def test_문구_필수_판정은_한_군데다() -> None:
    """요청 검증과 파이프라인이 각자 조건을 적어두면 갈렸을 때 한쪽만 통과한다.

    같은 실수를 #51 에서 이미 겪었다 (#76 리뷰). 스키마의 needs_copy 하나만 본다.
    """
    from app_core.schema import OutputType, needs_copy

    for value in get_args(OutputType):
        body = {
            "store_name": "연남 크로플",
            "industry": "cafe",
            "product": "크로플",
            "price": 4500,
            "output_type": value,
        }
        rejected = client.post("/ads/image", json=body).status_code == 422
        assert rejected is needs_copy(value), value


def test_낡은_style_키만_보내면_거절한다() -> None:
    """`extra="forbid"` 가 없어 낡은 키는 무시된다. `output_type` 에 기본값까지
    있으면 낡은 호출자가 **422 가 아니라 202** 로 통과하고, 포스터를 고른
    사장님이 감성형을 받는다 — 로그에도 안 남는다 (아인님 #77 지적).
    """
    body = {
        "store_name": "연남 크로플",
        "industry": "cafe",
        "product": "크로플",
        "price": 4500,
        "headline": "겨울 크로플",
    }
    assert client.post("/ads/image", json={**body, "style": "poster"}).status_code == 422
    assert client.post("/ads/image", json={**body, "output_type": "poster"}).status_code == 202


# ── 로그인 · 내 가게 ────────────────────────────────────────────


def _signup(username: str) -> str:
    """가입하고 토큰을 돌려준다."""
    res = client.post("/auth/signup", json={"username": username, "password": "비밀번호12345"})
    assert res.status_code == 201, res.text
    return str(res.json()["token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_토큰_없이는_내_가게를_못_본다() -> None:
    assert client.get("/stores").status_code == 401


def test_가입하고_가게를_넣으면_내_목록에_보인다() -> None:
    token = _signup("사장님1")
    assert client.get("/stores", headers=_bearer(token)).json() == []

    res = client.post(
        "/stores",
        headers=_bearer(token),
        json={
            "name": "행복한 순대국",
            "industry": "korean_food",
            "address": "서울시 은평구 불광동 56-7",
        },
    )
    assert res.status_code == 201
    assert client.get("/stores", headers=_bearer(token)).json()[0]["name"] == "행복한 순대국"


def test_남의_가게는_안_보인다() -> None:
    """가게 번호를 알아도 남의 것은 못 연다 — stores.get 이 user_id 로 거른다."""
    mine = _signup("사장님2")
    other = _signup("사장님3")
    store_id = client.post(
        "/stores", headers=_bearer(mine), json={"name": "내 가게", "industry": "cafe"}
    ).json()["id"]

    assert client.get(f"/stores/{store_id}", headers=_bearer(mine)).status_code == 200
    assert client.get(f"/stores/{store_id}", headers=_bearer(other)).status_code == 404


def test_토큰을_손대면_거절한다() -> None:
    """user_id 를 그대로 주고받으면 아무나 남의 번호를 적어 보낼 수 있다.
    서명이 그걸 막는다."""
    token = _signup("사장님4")
    user_id, _, sig = token.partition(".")
    위조 = f"{int(user_id) + 1}.{sig}"  # 번호만 바꿔치기
    assert client.get("/stores", headers=_bearer(위조)).status_code == 401
    # HTTP 헤더는 latin-1 이라 한글을 못 담는다 — 아무 말이나 ASCII 로 넣는다
    assert client.get("/stores", headers=_bearer("nonsense")).status_code == 401
    # Bearer 를 빼고 토큰만 보낸 경우
    assert client.get("/stores", headers={"Authorization": token}).status_code == 401


def test_로그인_실패는_어느_쪽이_틀렸는지_말하지_않는다() -> None:
    """구분해서 알려주면 어떤 아이디가 있는지 훑어볼 수 있다."""
    _signup("사장님5")
    없는_사람 = client.post(
        "/auth/login", json={"username": "없는사람", "password": "비밀번호12345"}
    )
    틀린_비번 = client.post("/auth/login", json={"username": "사장님5", "password": "틀린비밀번호"})
    assert 없는_사람.status_code == 틀린_비번.status_code == 401
    assert 없는_사람.json()["detail"] == 틀린_비번.json()["detail"]


def test_짧은_비밀번호는_거절한다() -> None:
    res = client.post("/auth/signup", json={"username": "짧은비번", "password": "1234"})
    assert res.status_code == 422


# ── 문구 · 손님 반응 ────────────────────────────────────────────
# 실제 LLM 은 부르지 않는다 (AGENTS.md). MODEL_PROFILE 기본값이 stub 이라
# 빈 결과 경로는 그대로 돌려볼 수 있고, 나머지는 등록 단계에서 걸린다.


def _store_of(token: str, industry: str = "korean_food") -> int:
    res = client.post(
        "/stores",
        headers=_bearer(token),
        json={
            "name": "행복한 순대국",
            "industry": industry,
            "address": "서울시 은평구 불광동 56-7",
        },
    )
    assert res.status_code == 201, res.text
    return int(res.json()["id"])


_BRIEF = {"product": "순대국", "price": 8000, "situation": "퇴근길", "tone": "따뜻하게"}


def test_문구와_평가는_로그인해야_한다() -> None:
    assert client.post("/ads/copies", json={"store_id": 1, **_BRIEF}).status_code == 401
    assert client.post("/ads/review", json={"store_id": 1, "ad_id": 1, **_BRIEF}).status_code == 401


def test_남의_가게로는_문구를_못_만든다() -> None:
    """가게 번호만 바꿔 남의 가게 이름으로 광고를 만들 수 있으면 안 된다."""
    mine, other = _signup("사장님6"), _signup("사장님7")
    store_id = _store_of(mine)
    res = client.post("/ads/copies", headers=_bearer(other), json={"store_id": store_id, **_BRIEF})
    assert res.status_code == 404


def test_문구를_못_만들면_이유를_말한다() -> None:
    """빈 목록을 조용히 돌려주면 화면은 고장인지 느린 건지 알 수 없다.

    MODEL_PROFILE 이 stub 이면 항상 빈 결과다 — 그 사실을 오류에 담아야
    ".env 를 보라"까지 갈 수 있다.
    """
    jobs.clear()
    token = _signup("사장님8")
    res = client.post(
        "/ads/copies", headers=_bearer(token), json={"store_id": _store_of(token), **_BRIEF}
    )
    assert res.status_code == 202

    body = _wait(res.json()["job_id"], timeout=10.0)
    assert body["status"] == "failed"
    assert body["error"] is not None
    # 타입 이름이 붙으면 사장님 화면에 "ValueError: ..." 가 그대로 뜬다
    assert not body["error"].startswith("ValueError")
    assert "stub" in body["error"]


def test_문구가_없으면_평가하지_않는다() -> None:
    """LLM 을 부르기 전에 걸러야 한다 — 1분 뒤에 "문구가 없다"고 하면 늦다."""
    jobs.clear()
    token = _signup("사장님9")
    res = client.post(
        "/ads/review",
        headers=_bearer(token),
        json={"store_id": _store_of(token), "ad_id": 999, **_BRIEF},
    )
    assert res.status_code == 202
    body = _wait(res.json()["job_id"], timeout=10.0)
    assert body["status"] == "failed"
    assert "문구를 먼저" in (body["error"] or "")


def test_json_결과는_폴링에_실려_온다() -> None:
    """이미지는 /jobs/{id}/image 로 따로 가져가지만 문구·평가는 JSON 이라
    상태와 함께 온다. 두 종류가 섞이지 않아야 한다."""
    jobs.clear()
    job = jobs.submit(lambda: {"ad_id": 7, "copies": []}, kind="json")
    body = _wait(job.id)
    assert body["status"] == "done"
    assert body["result"] == {"ad_id": 7, "copies": []}
    assert body["image_url"] is None


def test_json_작업의_이미지_주소는_404() -> None:
    """번호만 알면 누구나 부를 수 있는 주소다. 문구 작업의 결과는 dict 라
    그대로 흘려보내면 dict.save() 에서 500 이 난다 (귀한님 #66 리뷰)."""
    jobs.clear()
    job = jobs.submit(lambda: {"ad_id": 1, "copies": []}, kind="json")
    assert _wait(job.id)["status"] == "done"
    assert client.get(f"/jobs/{job.id}/image").status_code == 404


def test_이미지_작업은_json_결과를_싣지_않는다() -> None:
    jobs.clear()
    job = jobs.submit(lambda: "이미지인 척", kind="image")
    body = _wait(job.id)
    assert body["result"] is None
    assert body["image_url"] == f"/jobs/{job.id}/image"
