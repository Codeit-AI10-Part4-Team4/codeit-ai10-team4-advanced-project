"""photo_router 테스트 — 마스크 분석은 합성 이미지로, 비전 판정은 가짜 클라이언트로."""

from PIL import Image

from app_core import photo_router
from app_core.photo_router import mask_area, route_by_mask, route_photo


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


# ── 다제품 안전장치 (실측 2026-08-16: 2.6% 조각이 삭제되던 결함) ──────────


def test_부스러기를_뺀_조각_수를_센다():
    cut = _canvas([(8, 8, 40, 40), (48, 48, 56, 56), (60, 60, 62, 62)])  # 25% / 1.6% / 0.1%
    assert photo_router.significant_pieces(cut) == 2  # 부스러기는 안 센다


def test_상품이_여럿이면_비전이_generate라도_keep(monkeypatch):
    monkeypatch.setattr(photo_router, "judge_photo", lambda data, mime: "generate")
    cut = _canvas([(8, 8, 40, 40), (48, 48, 56, 56)])
    assert route_photo(b"", "image/jpeg", cut) == "keep"  # 새로 그리면 상품이 바뀐다


def test_상품이_여럿이면_비전을_아예_부르지_않는다(monkeypatch):
    def _boom(data, mime):
        raise AssertionError("다제품이면 판정 전에 keep 이어야 한다")

    monkeypatch.setattr(photo_router, "judge_photo", _boom)
    cut = _canvas([(8, 8, 40, 40), (48, 48, 56, 56)])
    assert route_photo(b"", "image/jpeg", cut) == "keep"


def test_전경이_넓어도_상품이_여럿이면_keep(monkeypatch):
    """면적 규칙(generate)보다 다제품 보존이 우선."""
    monkeypatch.setattr(photo_router, "judge_photo", lambda data, mime: "generate")
    cut = _canvas([(0, 0, 64, 30), (0, 34, 64, 64)])  # 합쳐서 94% — route_by_mask 면 generate
    assert photo_router.mask_area(cut) > 0.75
    assert route_photo(b"", "image/jpeg", cut) == "keep"


def test_상품이_하나면_cutout_그대로(monkeypatch):
    monkeypatch.setattr(photo_router, "judge_photo", lambda data, mime: "cutout")
    cut = _canvas([(8, 8, 40, 40), (60, 60, 62, 62)])  # 상품 1 + 부스러기
    assert route_photo(b"", "image/jpeg", cut) == "cutout"


def test_청소는_부스러기만_지우고_작은_상품은_남긴다():
    cut = _canvas([(8, 8, 40, 40), (48, 48, 56, 56), (60, 60, 62, 62)])
    cleaned = photo_router.remove_crumbs(cut)
    assert _alpha_at(cleaned, 20, 20) == 255  # 큰 상품
    assert _alpha_at(cleaned, 52, 52) == 255  # 작은 상품 — v1 은 여기를 지웠다
    assert _alpha_at(cleaned, 61, 61) == 0  # 부스러기


def test_빈_마스크는_청소해도_그대로다():
    assert _alpha_at(photo_router.remove_crumbs(_canvas([])), 30, 30) == 0
