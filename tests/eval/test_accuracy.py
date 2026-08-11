"""정확도 하네스 자체의 검증.

측정 도구가 틀리면 측정값도 틀린다. API 없이 확인할 수 있는 것만 본다 —
쌍 설계의 건전성, 시트 형식, 판별 판정 로직.
"""

from __future__ import annotations

import csv
from pathlib import Path

from accuracy import PAIRS, SHEET_COLUMNS, make_sheet


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


def test_sheet_hides_which_side_is_better(tmp_path: Path) -> None:
    """헤더에 good/bad 를 노출하면 블라인드가 아니다."""
    path = tmp_path / "labels.csv"
    make_sheet(path)
    text = path.read_text(encoding="utf-8-sig")
    assert "better" not in text
    assert "worse" not in text
