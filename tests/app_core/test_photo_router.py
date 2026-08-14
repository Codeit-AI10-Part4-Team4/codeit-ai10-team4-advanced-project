"""photo_router 테스트 — 마스크 분석은 합성 이미지로, 비전 판정은 가짜 응답으로."""

import sys
from types import SimpleNamespace

from PIL import Image

from app_core import photo_router
from app_core.photo_router import MaskStats, mask_stats, route_by_mask, route_photo


def _canvas(boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    """투명한 판(64×64)에 지정한 네모들만 불투명하게 채운 가짜 누끼 결과."""
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for box in boxes:
        im.paste((255, 255, 255, 255), box)
    return im


def test_빈_마스크는_면적이_0이다():
    s = mask_stats(_canvas([]))
    assert s.area == 0 and s.pieces == 0


def test_네모_하나는_조각_하나다():
    s = mask_stats(_canvas([(16, 16, 48, 48)]))
    assert s.pieces == 1
    assert 0.2 < s.area < 0.3
    assert s.largest == 1.0


def test_떨어진_네모_둘은_조각_둘이다():
    s = mask_stats(_canvas([(0, 0, 20, 20), (40, 40, 60, 60)]))
    assert s.pieces == 2


def test_전경이_화면을_다_덮으면_generate():
    assert route_by_mask(MaskStats(area=0.9, pieces=1, largest=1.0)) == "generate"


def test_보통_사진은_마스크만으로_못_정한다():
    assert route_by_mask(MaskStats(area=0.3, pieces=1, largest=1.0)) is None


def test_비전이_정한_갈래를_따른다(monkeypatch):
    monkeypatch.setattr(photo_router, "judge_photo", lambda data, mime: "keep")
    cut = _canvas([(16, 16, 48, 48)])
    assert route_photo(b"", "image/jpeg", cut) == "keep"


def test_누끼가_빈손이면_cutout_대신_keep(monkeypatch):
    monkeypatch.setattr(photo_router, "judge_photo", lambda data, mime: "cutout")
    cut = _canvas([(0, 0, 8, 8)])  # 화면의 1.5% — 오릴 게 없다
    assert route_photo(b"", "image/jpeg", cut) == "keep"


def _alpha_at(im: Image.Image, x: int, y: int) -> int:
    """(x, y) 픽셀의 알파값 — getpixel의 모호한 타입을 피해 bytes로 읽는다."""
    return im.getchannel("A").tobytes()[y * im.width + x]


def test_큰_덩어리만_남기고_작은_조각은_지운다():
    from app_core.photo_router import keep_largest

    cut = _canvas([(8, 8, 40, 40), (50, 50, 60, 60)])  # 주인공 + 딸려온 조각
    cleaned = keep_largest(cut)
    assert _alpha_at(cleaned, 20, 20) == 255  # 주인공은 그대로
    assert _alpha_at(cleaned, 55, 55) == 0  # 조각은 지워짐


def test_빈_마스크는_청소해도_그대로다():
    from app_core.photo_router import keep_largest

    cut = _canvas([])
    assert _alpha_at(keep_largest(cut), 30, 30) == 0


def _fake_openai(content):
    rsp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    class _Fake:
        class chat:
            class completions:
                create = staticmethod(lambda **kwargs: rsp)

    return lambda **kw: _Fake()


def test_판정_JSON이_깨져도_cutout으로_물러선다(monkeypatch):
    # 가짜 openai 모듈을 꽂는다 — 진짜 openai 가 없는 CI 에서도 이 시험은 돈다
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=_fake_openai("not json")))
    assert photo_router.judge_photo(b"x", "image/jpeg") == "cutout"


def test_판정_갈래가_엉뚱해도_cutout으로_물러선다(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "openai", SimpleNamespace(OpenAI=_fake_openai('{"route": "unknown"}'))
    )
    assert photo_router.judge_photo(b"x", "image/jpeg") == "cutout"
