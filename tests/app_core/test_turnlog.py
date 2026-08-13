"""턴 로그 — 실제 발화로 골든셋을 채우려고 남기는 기록."""

from pathlib import Path

import pytest

from app_core import turnlog
from app_core.schema import AdBriefDraft


@pytest.fixture(autouse=True)
def log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """테스트마다 빈 로그. 실제 data/ 를 건드리지 않는다."""
    path = tmp_path / "turns.jsonl"
    monkeypatch.setenv("ADS_TURNLOG", str(path))
    monkeypatch.setenv("ADS_TURNLOG_ENABLED", "1")
    return path


def record(utterance: str = "크로플이요", **kw) -> None:
    turnlog.record(
        utterance,
        kw.get("before", AdBriefDraft(goal="copy")),
        kw.get("after", AdBriefDraft(goal="copy", product="크로플")),
        kw.get("asked", "product"),
        kw.get("industry", "카페·디저트"),
    )


def test_한_턴이_남는다() -> None:
    record()
    entries = turnlog.read_all()
    assert len(entries) == 1
    assert entries[0]["utterance"] == "크로플이요"


def test_전후_상태를_같이_남긴다() -> None:
    """정정인지 최초 입력인지는 직전 상태를 봐야 안다."""
    record(
        "아니 6000원이요",
        before=AdBriefDraft(goal="copy", price=4500),
        after=AdBriefDraft(goal="copy", price=6000),
    )
    e = turnlog.read_all()[0]
    assert e["before"]["price"] == 4500
    assert e["after"]["price"] == 6000


def test_무엇을_물어보던_중이었는지_남긴다() -> None:
    """엉뚱한 답이 오는 이유를 여기서 찾는다."""
    record(asked="price")
    assert turnlog.read_all()[0]["asked"] == "price"


def test_여러_턴이_쌓인다() -> None:
    for said in ["크로플이요", "4500원", "따뜻하게"]:
        record(said)
    assert [e["utterance"] for e in turnlog.read_all()] == ["크로플이요", "4500원", "따뜻하게"]


def test_빈_발화는_안_남긴다() -> None:
    record("   ")
    assert turnlog.read_all() == []


def test_끌_수_있다(monkeypatch: pytest.MonkeyPatch) -> None:
    """실제 사장님에게 열 때는 꺼야 한다 — 남는 게 발화 원문이다."""
    monkeypatch.setenv("ADS_TURNLOG_ENABLED", "0")
    record()
    assert turnlog.read_all() == []


def test_기본은_켜짐이다(monkeypatch: pytest.MonkeyPatch) -> None:
    """골든셋의 원천이라 꺼져 있으면 아무도 안 켜고 발화가 안 쌓인다.
    주석과 코드가 어긋나 있던 자리라 값으로 못을 박아둔다.
    """
    monkeypatch.delenv("ADS_TURNLOG_ENABLED", raising=False)
    assert turnlog.enabled() is True


def test_로그가_없으면_빈_목록() -> None:
    assert turnlog.read_all() == []


def test_깨진_줄은_건너뛴다(log_file: Path) -> None:
    """로그 하나 깨졌다고 전부 못 읽으면 안 된다."""
    record("크로플이요")
    log_file.write_text(log_file.read_text(encoding="utf-8") + "{깨진 줄\n", encoding="utf-8")
    record("4500원")
    assert [e["utterance"] for e in turnlog.read_all()] == ["크로플이요", "4500원"]


def test_쓰기에_실패해도_안_터진다(monkeypatch: pytest.MonkeyPatch) -> None:
    """로그가 안 남는 것보다 대화가 끊기는 게 더 나쁘다."""
    monkeypatch.setenv("ADS_TURNLOG", "/존재하지않는경로/x/turns.jsonl")
    record()  # 예외가 나면 안 된다
