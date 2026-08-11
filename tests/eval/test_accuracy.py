"""정확도 하네스 자체의 검증.

측정 도구가 틀리면 측정값도 틀린다. API 없이 확인할 수 있는 것만 본다 —
쌍 설계의 건전성, 시트 형식, 판별 판정 로직.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from accuracy import PAIRS, SHEET_COLUMNS, blind_key, make_sheet


def test_pairs_change_exactly_one_thing() -> None:
    """한 쌍에서 두 가지를 바꾸면 무엇 때문에 갈렸는지 알 수 없다."""
    for pair in PAIRS:
        good, bad = pair.better, pair.worse
        differs = sum(
            [
                good.brief.price != bad.brief.price,
                good.copy.headline != bad.copy.headline or good.copy.sub != bad.copy.sub,
                good.brief.product != bad.brief.product,
            ]
        )
        assert differs == 1, f"{pair.name}: {differs}가지가 다르다"


def test_pair_keys_are_unique() -> None:
    keys = [ad.key for pair in PAIRS for ad in (pair.better, pair.worse)]
    assert len(set(keys)) == len(keys)


def test_trade_area_pairs_cite_a_measured_number() -> None:
    """상권 쌍은 실측 수치에 근거해야 한다.

    근거 없는 쌍은 패널이 틀려도 패널 탓인지 우리 탓인지 알 수 없다.
    판단으로 만든 쌍은 `보편` 로 분리해 따로 집계한다.
    """
    grounded = [p for p in PAIRS if p.kind == "상권"]
    assert len(grounded) >= 3, "상권 쌍이 너무 적으면 그라운딩을 측정하지 못한다"
    for pair in grounded:
        assert any(ch.isdigit() for ch in pair.why), f"{pair.name}: 실측 수치가 없다"


def test_pair_kinds_are_known() -> None:
    assert {p.kind for p in PAIRS} <= {"상권", "보편"}
    for pair in PAIRS:
        assert pair.why.strip(), pair.name


def test_sheet_is_blind_and_shuffled(tmp_path: Path) -> None:
    """시트가 좋은 쪽·나쁜 쪽 순서대로면 사람이 눈치챈다."""
    path = tmp_path / "labels.csv"
    make_sheet(path)

    with path.open(encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))

    assert [*rows[0]] == SHEET_COLUMNS
    assert len(rows) == len(PAIRS) * 2
    assert all(r["사람점수_0_100"] == "" for r in rows)

    ordered = [ad.key for pair in PAIRS for ad in (pair.better, pair.worse)]
    assert [r["ad_key"] for r in rows] != ordered


def test_sheet_never_contains_a_raw_ad_key(tmp_path: Path) -> None:
    """정답이 첫 칸에 그대로 실려 있었다 (아인님 제보, f429a0c).

    이전 테스트는 `"better"` / `"worse"` 문자열만 봤는데 실제 키는 `time_good` ·
    `price_bad` 였다. **내가 쓴 단어가 아니라 성질을 검사해야 한다** — 키 목록을
    `PAIRS` 에서 직접 가져오면 이름을 바꿔도 따라온다.
    """
    path = tmp_path / "labels.csv"
    make_sheet(path)
    with path.open(encoding="utf-8-sig") as fp:
        keys = {row["ad_key"] for row in csv.DictReader(fp)}

    for pair in PAIRS:
        for ad in (pair.better, pair.worse):
            assert ad.key not in keys, f"{ad.key} 가 시트에 그대로 실렸다"


@pytest.mark.parametrize("token", ["good", "bad", "better", "worse", "정답"])
def test_ad_key_column_has_no_side_marking_word(tmp_path: Path, token: str) -> None:
    """식별자가 어느 쪽이 이길지 암시하면 안 된다.

    **문구 칸은 검사하지 않는다.** 광고 문구에 "좋은"이 들어가는 것은 사람이
    판단할 내용이라, 파일 전체를 훑으면 정상 문구까지 막는다 —
    `"혼자 먹기 딱 좋은 크기"` 가 실제로 걸렸다.
    """
    path = tmp_path / "labels.csv"
    make_sheet(path)
    with path.open(encoding="utf-8-sig") as fp:
        keys = [row["ad_key"] for row in csv.DictReader(fp)]
    assert all(token not in key for key in keys)


def test_blinded_keys_are_unique_and_stable() -> None:
    """가림용 키가 겹치면 `--score` 에서 다른 광고의 점수가 섞인다."""
    keys = [ad.key for pair in PAIRS for ad in (pair.better, pair.worse)]
    blinded = [blind_key(k) for k in keys]

    assert len(set(blinded)) == len(keys)
    assert blinded == [blind_key(k) for k in keys]  # 같은 입력 → 같은 출력
    assert all(b not in k and k not in b for k, b in zip(keys, blinded, strict=True))


def test_scoring_can_map_blinded_keys_back(tmp_path: Path) -> None:
    """가려도 되돌아와야 대조가 된다 — 시트를 채운 뒤 그 행이 어느 광고인지."""
    path = tmp_path / "labels.csv"
    make_sheet(path)

    with path.open(encoding="utf-8-sig") as fp:
        rows = list(csv.DictReader(fp))

    lookup = {blind_key(ad.key): ad for pair in PAIRS for ad in (pair.better, pair.worse)}
    for row in rows:
        ad = lookup[row["ad_key"]]
        assert ad.copy.headline == row["headline"]


def test_old_sheets_with_raw_keys_still_readable() -> None:
    """가리기 전에 만든 시트도 읽혀야 한다 — 팀원이 이미 채우고 있을 수 있다."""
    import accuracy

    ads = [ad for pair in PAIRS for ad in (pair.better, pair.worse)]
    lookup = {ad.key: ad for ad in ads} | {blind_key(ad.key): ad for ad in ads}
    assert set(lookup) >= {ads[0].key, blind_key(ads[0].key)}
    assert hasattr(accuracy, "blind_key")
