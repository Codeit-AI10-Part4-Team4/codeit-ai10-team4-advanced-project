"""실제 상품 사진의 내용은 유지하고 촬영 상태만 보수적으로 보정한다."""

from __future__ import annotations

import math

from PIL import Image, ImageFilter, ImageOps

_SAMPLE_SIZE = 256
_GAMMA_MIN = 0.90
_GAMMA_MAX = 1.10
_NORMAL_DARK = 108
_NORMAL_BRIGHT = 150
_WHITE_BALANCE_LIMIT = 0.025
_CONTRAST_STRENGTH = 0.06
_CANVAS_BLUR = 24


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_rgb(photo: Image.Image) -> Image.Image:
    """EXIF 방향을 반영하고 투명 이미지는 흰 바탕의 RGB로 바꾼다."""
    oriented = ImageOps.exif_transpose(photo)

    if "A" in oriented.getbands() or "transparency" in oriented.info:
        rgba = oriented.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(white, rgba).convert("RGB")

    return oriented.convert("RGB")


def fit_photo_canvas(photo: Image.Image, size: tuple[int, int]) -> Image.Image:
    """사진 전체 비율을 지키고 남는 공간만 같은 장면의 흐린 배경으로 채운다."""
    source = _to_rgb(photo)
    if source.size == size:
        return source

    background = ImageOps.fit(
        source,
        size,
        method=Image.Resampling.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(_CANVAS_BLUR))
    foreground = ImageOps.contain(
        source,
        size,
        method=Image.Resampling.LANCZOS,
    )
    x = (size[0] - foreground.width) // 2
    y = (size[1] - foreground.height) // 2
    background.paste(foreground, (x, y))
    return background


def _sample(photo: Image.Image) -> Image.Image:
    """통계 계산용 작은 복사본. 실제 결과 사진은 줄이지 않는다."""
    sampled = photo.copy()
    sampled.thumbnail(
        (_SAMPLE_SIZE, _SAMPLE_SIZE),
        Image.Resampling.LANCZOS,
    )
    return sampled


def _neutral_gains(
    sampled: Image.Image,
) -> tuple[float, float, float] | None:
    """밝고 중립적인 픽셀로 아주 약한 화이트밸런스를 계산한다."""
    red = green = blue = count = 0

    for y in range(sampled.height):
        for x in range(sampled.width):
            pixel = sampled.getpixel((x, y))
            if not isinstance(pixel, tuple):
                continue

            r, g, b = int(pixel[0]), int(pixel[1]), int(pixel[2])
            brightness = (299 * r + 587 * g + 114 * b) // 1000
            channel_gap = max(r, g, b) - min(r, g, b)

            if 96 <= brightness <= 245 and channel_gap <= max(
                12,
                int(brightness * 0.16),
            ):
                red += r
                green += g
                blue += b
                count += 1

    minimum = max(1, sampled.width * sampled.height // 50)
    if count < minimum:
        return None

    means = (red / count, green / count, blue / count)
    target = sum(means) / 3

    low = 1 - _WHITE_BALANCE_LIMIT
    high = 1 + _WHITE_BALANCE_LIMIT

    return (
        _clamp(target / means[0], low, high),
        _clamp(target / means[1], low, high),
        _clamp(target / means[2], low, high),
    )


def _balance_lut(gain: float) -> list[int]:
    """검정과 흰색 끝점은 그대로 두고 중간 색만 살짝 움직인다."""
    values = []

    for value in range(256):
        curve = 2 * value * (255 - value) / 255
        corrected = round(value + (gain - 1) * curve)
        values.append(max(0, min(255, corrected)))

    return values


def _apply_white_balance(
    photo: Image.Image,
    gains: tuple[float, float, float] | None,
) -> Image.Image:
    if gains is None:
        return photo

    red, green, blue = photo.split()
    return Image.merge(
        "RGB",
        (
            red.point(_balance_lut(gains[0])),
            green.point(_balance_lut(gains[1])),
            blue.point(_balance_lut(gains[2])),
        ),
    )


def _median_brightness(photo: Image.Image) -> int:
    histogram = ImageOps.grayscale(photo).histogram()
    halfway = sum(histogram) / 2
    accumulated = 0

    for value, count in enumerate(histogram):
        accumulated += count
        if accumulated >= halfway:
            return value

    return 128


def _exposure_gamma(median: int) -> float:
    if _NORMAL_DARK <= median <= _NORMAL_BRIGHT:
        return 1.0

    if median <= 0 or median >= 255:
        return 1.0

    target = _NORMAL_DARK if median < _NORMAL_DARK else _NORMAL_BRIGHT
    gamma = math.log(target / 255) / math.log(median / 255)
    return _clamp(gamma, _GAMMA_MIN, _GAMMA_MAX)


def _gamma_lut(gamma: float) -> list[int]:
    return [round(255 * ((value / 255) ** gamma)) for value in range(256)]


def _contrast_lut() -> list[int]:
    values = []

    for value in range(256):
        normalized = value / 255
        smooth = normalized * normalized * (3 - 2 * normalized)
        mixed = (1 - _CONTRAST_STRENGTH) * normalized + _CONTRAST_STRENGTH * smooth
        values.append(round(255 * mixed))

    return values


def enhance_uploaded_photo(photo: Image.Image) -> Image.Image:
    """상품 내용과 좌표는 유지하고 촬영 상태만 보수적으로 보정한다."""
    oriented = ImageOps.exif_transpose(photo)
    icc_profile = oriented.info.get("icc_profile")

    corrected = _to_rgb(photo)
    gains = _neutral_gains(_sample(corrected))
    corrected = _apply_white_balance(corrected, gains)

    median = _median_brightness(_sample(corrected))
    gamma = _exposure_gamma(median)
    corrected = corrected.point(_gamma_lut(gamma) * 3)
    corrected = corrected.point(_contrast_lut() * 3)

    if icc_profile is not None:
        corrected.info["icc_profile"] = icc_profile

    return corrected
