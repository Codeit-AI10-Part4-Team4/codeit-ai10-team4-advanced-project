"""photo_router 테스트 — 마스크 분석은 합성 이미지로, 비전 판정은 가짜 클라이언트로."""

from PIL import Image

from app_core import photo_router
from app_core.photo_router import keep_largest, mask_area, route_by_mask, route_photo


def _canvas(boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    """투명한 판(64×64)에 지정한 네모들만 불투명하게 채운 가짜 누끼 결과."""
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for box in boxes:
        im.paste((255, 255, 255, 255), box)
    return im


def _alpha_at(im: Image.Image, x: int, y: int) -> int:
    """(x, y) 픽셀의 알파값 — getpixel의 모호한 타입을 피해 bytes로 읽는다."""
    return im.getchannel("A").tobytes()[y * im.width + x]


class _FakeVision:
    """가짜 비전 클라이언트 — 정해둔 답을 주거나, 예외를 던진다."""

    def __init__(self, out):
        self._out = out

    def read_image(self, system: str, image: bytes, mime: str) -> dict:
        if isinstance(self._out, Exception):
            raise self._out
        return self._out


# ── 마스크 ────────────────────────────────────────────────


def test_빈_마스크는_면적이_0이다():
    assert mask_area(_canvas([])) == 0


def test_네모_하나의_면적을_잰다():
    assert 0.2 < mask_area(_canvas([(16, 16, 48, 48)])) < 0.3


def test_전경이_화면을_다_덮으면_generate():
    assert route_by_mask(0.9) == "generate"


def test_보통_사진은_마스크만으로_못_정한다():
    assert route_by_mask(0.3) is None


# ── 갈래 판정 ──────────────────────────────────────────────


def test_비전이_정한_갈래를_따른다(monkeypatch):
    monkeypatch.setattr(photo_router, "judge_photo", lambda data, mime: "keep")
    cut = _canvas([(16, 16, 48, 48)])
    assert route_photo(b"", "image/jpeg", cut) == "keep"


def test_누끼가_빈손이면_cutout_대신_keep(monkeypatch):
    monkeypatch.setattr(photo_router, "judge_photo", lambda data, mime: "cutout")
    cut = _canvas([(0, 0, 8, 8)])  # 화면의 1.5% — 오릴 게 없다
    assert route_photo(b"", "image/jpeg", cut) == "keep"


def test_판정_스텁이면_cutout으로_물러선다():
    assert photo_router.judge_photo(b"x", "image/jpeg", client=_FakeVision({})) == "cutout"


def test_판정_갈래가_엉뚱해도_cutout으로_물러선다():
    fake = _FakeVision({"route": "unknown"})
    assert photo_router.judge_photo(b"x", "image/jpeg", client=fake) == "cutout"


def test_외부_호출이_실패해도_cutout으로_물러선다():
    fake = _FakeVision(RuntimeError("네트워크 끊김"))
    assert photo_router.judge_photo(b"x", "image/jpeg", client=fake) == "cutout"


def test_판정은_공용_비전_클라이언트를_쓴다(monkeypatch):
    fake = _FakeVision({"route": "keep"})
    monkeypatch.setattr(photo_router.llm, "get_vision_client", lambda: fake)
    assert photo_router.judge_photo(b"x", "image/jpeg") == "keep"


# ── 누끼 청소 ──────────────────────────────────────────────


def test_큰_덩어리만_남기고_작은_조각은_지운다():
    cut = _canvas([(8, 8, 40, 40), (50, 50, 60, 60)])  # 주인공 + 딸려온 조각
    cleaned = keep_largest(cut)
    assert _alpha_at(cleaned, 20, 20) == 255  # 주인공은 그대로
    assert _alpha_at(cleaned, 55, 55) == 0  # 조각은 지워짐


def test_빈_마스크는_청소해도_그대로다():
    assert _alpha_at(keep_largest(_canvas([])), 30, 30) == 0
