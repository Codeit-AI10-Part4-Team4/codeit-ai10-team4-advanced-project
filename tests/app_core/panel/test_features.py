"""build_features 검증.

DuckDB 파일이 있어야 도는 테스트라 없으면 건너뛴다 (CI 에는 데이터가 없다).
로컬에서 `python etl/load_csv.py` 를 돌린 뒤 실행하면 검증된다.

골든 픽스처(`features_yeoksam_20261.json`)와 대조하는 것이 핵심이다.
픽스처는 평가 쪽(B)이 개발 기준으로 쓰므로, 여기서 어긋나면 계약이 깨진 것이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_core.panel.features import (
    CATEGORY_MAP,
    DB_PATH,
    NoTradeAreaError,
    build_features,
)

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="data/panel.duckdb 없음 — etl/load_csv.py 를 먼저 실행"
)

#: 역삼역 2호선 부근. 상권 중심까지 50m 로 이 상권에 붙는다.
YEOKSAM = (127.0365, 37.5005)
FIXTURE = Path(__file__).parents[2] / "fixtures" / "features_yeoksam_20261.json"


@pytest.fixture(scope="module")
def yeoksam_cafe() -> dict:
    return build_features("서울 강남구 역삼동", "cafe", coord=YEOKSAM)


def test_골든_픽스처와_일치한다(yeoksam_cafe: dict) -> None:
    want = json.loads(FIXTURE.read_text(encoding="utf-8"))["features"]
    assert yeoksam_cafe == want


def test_비중은_합이_1이다(yeoksam_cafe: dict) -> None:
    for key in ("gender_share", "age_share", "time_share", "foot_age_share"):
        assert sum(yeoksam_cafe[key].values()) == pytest.approx(1.0, abs=0.01), key


def test_미상_매출을_정규화해도_원래_합계를_남긴다(yeoksam_cafe: dict) -> None:
    # 성별·연령 합계가 1이 아니다(법인카드 등). 정규화 후에도 원래 비율을 알아야
    # 신뢰도 낮음을 판단할 수 있다.
    assert 0 < yeoksam_cafe["demo_coverage"] < 1


def test_업종_데이터가_없으면_상권_전체로_폴백한다() -> None:
    # photostudio 는 서울시 상권 데이터에 대응 업종이 없다 → 에러 대신 폴백.
    f = build_features("서울 강남구 역삼동", "photostudio", coord=YEOKSAM)
    assert f["is_category_fallback"] is True
    assert f["category_cds"] == []
    assert sum(f["age_share"].values()) == pytest.approx(1.0, abs=0.01)


def test_모르는_업종도_폴백으로_평가된다() -> None:
    f = build_features("서울 강남구 역삼동", "존재하지_않는_업종", coord=YEOKSAM)
    assert f["is_category_fallback"] is True


def test_합산_업종은_단일보다_커버리지가_넓다() -> None:
    # fitness 는 스포츠클럽 하나가 아니라 4개 코드를 합쳐 읽는다 (docs/07 §4.5).
    assert len(CATEGORY_MAP["fitness"]) == 4
    f = build_features("서울 강남구 역삼동", "fitness", coord=YEOKSAM)
    assert f["is_category_fallback"] is False


def test_가장_가까운_상권에_붙는다(yeoksam_cafe: dict) -> None:
    assert yeoksam_cafe["area_nm"] == "역삼역"
    assert yeoksam_cafe["match_distance_m"] < 200


def test_서울_밖_주소는_억지로_붙이지_않는다() -> None:
    """부산 해운대(313km)가 강남 상권으로 붙던 버그. 사장님 언어로 막는다."""
    with pytest.raises(NoTradeAreaError, match="서울 안의 주소가 아닌"):
        build_features("", "cafe", coord=(129.15993, 35.17942))


def test_서울_변두리는_통과한다() -> None:
    """실측 최원거리(도봉동 산자락 2,349m)가 상한 3,000m 안에 있다."""
    f = build_features("", "cafe", coord=(127.0155, 37.6893))  # 도봉구 도봉동
    assert f["match_distance_m"] < 3_000
