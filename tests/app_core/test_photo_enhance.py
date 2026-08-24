"""실제 상품 사진을 새로 그리지 않는 보정 계약."""

from PIL import Image

from app_core.photo_enhance import enhance_uploaded_photo


def _rgb_at(photo: Image.Image, xy: tuple[int, int]) -> tuple[int, int, int]:
    pixel = photo.getpixel(xy)
    assert isinstance(pixel, tuple)
    assert len(pixel) >= 3
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def test_EXIF_회전을_실제_픽셀_방향에_반영한다() -> None:
    photo = Image.new("RGB", (3, 2))
    values = (
        20,
        40,
        60,
        140,
        160,
        180,
    )

    for index, value in enumerate(values):
        photo.putpixel(
            (index % 3, index // 3),
            (value, value, value),
        )

    exif = photo.getexif()
    exif[274] = 6
    photo.info["exif"] = exif.tobytes()

    result = enhance_uploaded_photo(photo)

    assert result.size == (2, 3)

    assert _rgb_at(result, (0, 0))[0] > _rgb_at(result, (1, 0))[0]
    assert _rgb_at(result, (0, 0))[0] < _rgb_at(result, (0, 1))[0] < _rgb_at(result, (0, 2))[0]
    assert _rgb_at(result, (1, 0))[0] < _rgb_at(result, (1, 1))[0] < _rgb_at(result, (1, 2))[0]


def test_입력사진을_직접_수정하지_않는다() -> None:
    photo = Image.new("RGB", (8, 6), (90, 100, 110))
    before = photo.tobytes()

    result = enhance_uploaded_photo(photo)

    assert result is not photo
    assert photo.size == (8, 6)
    assert photo.tobytes() == before


def test_같은사진은_항상_같은결과를_만든다() -> None:
    photo = Image.new("RGB", (12, 8))

    for y in range(photo.height):
        for x in range(photo.width):
            photo.putpixel(
                (x, y),
                (
                    30 + x * 5,
                    40 + y * 7,
                    50 + (x + y) * 3,
                ),
            )

    first = enhance_uploaded_photo(photo)
    second = enhance_uploaded_photo(photo)

    assert first.size == second.size
    assert first.tobytes() == second.tobytes()


def test_어두운사진은_과하지_않게_밝힌다() -> None:
    photo = Image.new("RGB", (20, 10), (45, 45, 45))

    result = enhance_uploaded_photo(photo)
    value = _rgb_at(result, (0, 0))[0]

    assert 45 < value <= 65


def test_정상밝기사진은_불필요하게_바꾸지_않는다() -> None:
    photo = Image.new("RGB", (20, 10), (128, 128, 128))
    photo.info["icc_profile"] = b"test-profile"

    result = enhance_uploaded_photo(photo)

    assert result.mode == "RGB"
    assert result.size == photo.size
    assert result.getpixel((0, 0)) == (128, 128, 128)
    assert result.info["icc_profile"] == b"test-profile"


def test_투명영역은_흰배경으로_안전하게_합성한다() -> None:
    photo = Image.new("RGBA", (2, 1))
    photo.putpixel((0, 0), (255, 0, 0, 0))
    photo.putpixel((1, 0), (0, 0, 255, 255))

    result = enhance_uploaded_photo(photo)

    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert result.getpixel((1, 0)) == (0, 0, 255)


def test_상품표식의_위치를_옮기거나_복제하지_않는다() -> None:
    photo = Image.new("RGB", (7, 5), (128, 128, 128))
    marker = (4, 2)
    photo.putpixel(marker, (255, 0, 0))

    result = enhance_uploaded_photo(photo)

    red_pixels = []

    for y in range(result.height):
        for x in range(result.width):
            red, green, blue = _rgb_at(result, (x, y))
            if red > green * 2 and red > blue * 2:
                red_pixels.append((x, y))

    assert red_pixels == [marker]


def test_명암순서를_뒤집거나_끝값으로_뭉개지_않는다() -> None:
    photo = Image.new("RGB", (254, 1))

    for x in range(photo.width):
        value = x + 1
        photo.putpixel((x, 0), (value, value, value))

    result = enhance_uploaded_photo(photo)
    values = [_rgb_at(result, (x, 0))[0] for x in range(result.width)]

    assert values == sorted(values)
    assert min(values) > 0
    assert max(values) < 255
