"""compose 부품 테스트 — 폰트·GPU 없이 돌도록 작은 이미지와 기본 폰트를 쓴다."""

from PIL import Image, ImageDraw, ImageFont

from app_core import compose, fonts


def _fake_font(role: str, size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """글꼴 선택은 `fonts` 한 곳에서만 한다 — 대역도 거기에 세운다."""
    return ImageFont.load_default(size)


def _pixels(im: Image.Image) -> list[tuple[int, int, int]]:
    """모든 픽셀 (R, G, B) — getdata/getpixel 의 모호한 타입을 피해 bytes 로 읽는다."""
    raw = im.convert("RGB").tobytes()
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]


def _px(im: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    """(x, y) 픽셀 하나."""
    return _pixels(im.crop((x, y, x + 1, y + 1)))[0]


def test_gradient_background_size_and_mode():
    bg = compose.make_gradient_background(size=(64, 64))
    assert bg.size == (64, 64)
    assert bg.mode == "RGB"
    assert _px(bg, 0, 0) == (255, 244, 228)


def test_compose_ad_returns_rgb_canvas(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    product = Image.new("RGBA", (40, 30), (255, 0, 0, 255))
    ad = compose.compose_ad(product, "헤드라인", "서브 문구", size=(256, 256))
    assert ad.size == (256, 256)
    assert ad.mode == "RGB"


def test_compose_ad_uses_given_background(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    product = Image.new("RGBA", (40, 30), (255, 0, 0, 255))
    blue = Image.new("RGB", (64, 64), (0, 0, 255))
    ad = compose.compose_ad(product, "제목", size=(256, 256), background=blue)
    assert _px(ad, 5, 250) == (0, 0, 255)


def test_compose_ad_without_product(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    ad = compose.compose_ad(None, "사진 없는 광고", "문구만으로", size=(256, 256))
    assert ad.size == (256, 256)
    assert ad.mode == "RGB"


# ── v2 규칙 (문서/compose_v2_규칙명세.md) ──────────────────────────


def _checker(size: tuple[int, int], rows: range | None = None) -> Image.Image:
    """체스판(복잡) 배경. rows 를 주면 그 줄만 체스판, 나머지는 회색 단색."""
    w, h = size
    bg = Image.new("RGB", size, (200, 200, 200))
    d = ImageDraw.Draw(bg)
    for y in rows if rows is not None else range(h):
        for x in range(0, w, 8):
            color = (0, 0, 0) if (x // 8 + y // 8) % 2 == 0 else (255, 255, 255)
            d.line([(x, y), (x + 7, y)], fill=color)
    return bg


def _split_bg(size=(256, 256), *, busy_top: bool) -> Image.Image:
    """한쪽은 단색(단순), 다른 쪽은 체스판(복잡)인 배경."""
    _, h = size
    return _checker(size, range(h // 3) if busy_top else range(h * 2 // 3, h))


def test_제품이_있으면_상단형():
    assert compose.pick_zone(Image.new("RGB", (256, 256)), Image.new("RGBA", (10, 10))) == "top"


def test_제품이_없으면_덜_복잡한_쪽():
    assert compose.pick_zone(_split_bg(busy_top=True), None) == "bottom"
    assert compose.pick_zone(_split_bg(busy_top=False), None) == "top"


def test_단순한_영역은_대비색_어두운_배경엔_밝은_글자(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    dark = Image.new("RGB", (256, 256), (20, 20, 20))
    ad = compose.compose_ad(None, "제목", size=(256, 256), background=dark)
    assert _px(ad, 2, 2) == (20, 20, 20)  # 판이 안 깔렸으니 모서리는 배경색 그대로
    top = ad.crop(compose.zone_box(ad.size, "top"))
    assert max(p[0] for p in _pixels(top)) > 200  # 흰 글자 픽셀 존재


def test_단순한_밝은_배경엔_어두운_글자(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    light = Image.new("RGB", (256, 256), (240, 240, 240))
    ad = compose.compose_ad(None, "제목", size=(256, 256), background=light)
    top = ad.crop(compose.zone_box(ad.size, "top"))
    assert min(p[0] for p in _pixels(top)) < 60


def test_복잡한_영역엔_방향이_맞는_그라데이션_판(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    bg = _checker((256, 256))  # 상·하단 모두 복잡 → std > 55 → 판
    zone = compose.pick_zone(bg, None)
    ad = compose.compose_ad(None, "제목", size=(256, 256), background=bg)
    y_dense = 1 if zone == "top" else 254  # 판의 진한 끝
    y_far = 254 if zone == "top" else 1
    row_dense = [_px(ad, x, y_dense)[0] for x in range(0, 256, 3)]
    row_far = [_px(ad, x, y_far)[0] for x in range(0, 256, 3)]
    assert max(row_dense) < max(row_far)  # 진한 쪽이 더 어둡다 = 방향이 맞다


def test_긴_제목은_최대_2줄이고_안전영역을_안_넘는다(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    font, lines = compose.wrap_to_fit(
        "아주 긴 제목 문구가 여기에 계속 이어집니다 정말로", 120, "display", 40, 12
    )
    assert 1 <= len(lines) <= 2
    assert all(font.getlength(line) <= 120 for line in lines)


def test_제품은_사용_가능_상자_안에_들어가고_그림자가_뒤에_있다(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    white = Image.new("RGB", (256, 256), (255, 255, 255))
    product = Image.new("RGBA", (300, 300), (255, 0, 0, 255))  # 상자보다 큰 제품
    ad = compose.compose_ad(product, "제목", size=(256, 256), background=white)
    red = (255, 0, 0)
    assert red not in _pixels(ad.crop((0, int(256 * 0.93), 256, 256)))  # 하단 8% 여백
    assert red not in _pixels(ad.crop((0, 0, int(256 * 0.07) - 1, 256)))  # 좌측 7% 여백
    reds = [y for y in range(256) if _px(ad, 128, y) == red]
    below = _px(ad, 128, min(255, max(reds) + 3))
    assert below[0] < 250  # 제품 바로 아래는 그림자로 흰색보다 어둡다


def test_제목은_display_부제는_body_light_역할(monkeypatch):
    seen = []

    def _spy(role, size):
        seen.append(role)
        return ImageFont.load_default(size)

    monkeypatch.setattr(fonts, "load", _spy)
    compose.compose_ad(None, "제목", "부제", size=(256, 256))
    assert "display" in seen and "body_light" in seen


def test_갈색_외곽선이_사라졌다(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    white = Image.new("RGB", (256, 256), (255, 255, 255))
    ad = compose.compose_ad(None, "제목", size=(256, 256), background=white)
    assert (60, 35, 15) not in set(_pixels(ad))


def test_다른_크기에서도_비율_규칙_유지():
    box_a = compose.zone_box((1080, 1080), "top")
    box_b = compose.zone_box((540, 675), "top")
    assert round(box_a[0] / 1080, 2) == round(
        box_b[0] / 540, 2
    )  # 좌우 여백 비율 동일(정수 반올림 허용)
    assert round(box_a[3] / 1080, 2) == round(box_b[3] / 675, 2)  # 영역 높이 비율 동일


def test_회귀_std_50에서_55_사이_배경은_판이_깔린다(monkeypatch):
    """꽃집_밝음(53.5)·꽃집_복잡(50.5) — 실제 배경 스냅샷에서 판이 없어 안 읽혔던 구간."""
    monkeypatch.setattr(fonts, "load", _fake_font)
    # 밝은 회색 바탕에 어두운 얼룩을 섞어 std 를 50~55 로 맞춘 배경
    bg = Image.new("RGB", (256, 256), (170, 170, 170))
    d = ImageDraw.Draw(bg)
    for y in range(0, 256, 6):
        d.line([(0, y), (256, y)], fill=(60, 60, 60), width=2)
    _, std = compose.zone_stats(bg, "top")
    assert 50 < std < 55, f"테스트 배경 std={std:.1f} — 구간을 벗어남"
    ad = compose.compose_ad(None, "제목", size=(256, 256), background=bg)
    # 판이 깔리면 상단 첫 줄이 원래 회색(170)보다 확실히 어둡다
    assert max(_px(ad, x, 1)[0] for x in range(0, 256, 5)) < 150


def test_긴_문구_실제_렌더링이_안전영역을_안_넘는다(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    white = Image.new("RGB", (256, 256), (255, 255, 255))
    ad = compose.compose_ad(
        None,
        "아주 긴 제목 문구가 여기에 계속 이어집니다 정말로 길게",
        "부제도 꽤 길게 써서 넘치는지 봅니다",
        size=(256, 256),
        background=white,
    )
    margin = int(256 * 0.07) - 1
    assert all(p[0] > 200 for p in _pixels(ad.crop((0, 0, margin, 256))))  # 좌 여백
    assert all(p[0] > 200 for p in _pixels(ad.crop((256 - margin, 0, 256, 256))))  # 우 여백
    assert all(p[0] > 200 for p in _pixels(ad.crop((0, int(256 * 0.36), 256, 256))))  # 글자 영역 밖
    assert any(
        p[0] < 60 for p in _pixels(ad.crop(compose.zone_box(ad.size, "top")))
    )  # 영역 안엔 글자가 실제로 있다


def test_540x675_실제_출력에서_제품과_글자가_캔버스_안에_있다(monkeypatch):
    monkeypatch.setattr(fonts, "load", _fake_font)
    white = Image.new("RGB", (540, 675), (255, 255, 255))
    product = Image.new("RGBA", (400, 400), (255, 0, 0, 255))
    ad = compose.compose_ad(product, "제목", "부제", size=(540, 675), background=white)
    assert ad.size == (540, 675)
    red = (255, 0, 0)
    assert red not in _pixels(ad.crop((0, int(675 * 0.93), 540, 675)))  # 하단 8%
    margin = int(540 * 0.07) - 1  # 정수 반올림 1px 여유
    assert red not in _pixels(ad.crop((0, 0, margin, 675)))  # 좌 7%
    assert red not in _pixels(ad.crop((540 - margin, 0, 540, 675)))  # 우 7%
    assert red in _pixels(ad)  # 제품이 실제로 그려짐
