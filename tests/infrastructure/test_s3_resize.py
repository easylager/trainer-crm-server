"""Пересжатие фото на загрузке: JPEG не больше лимита больше не проходит «как есть»."""

from __future__ import annotations

import io

from PIL import Image

from scripts.recompress_arena_heroes import plan_one
from src.infrastructure.s3 import PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY, _resize_image


def _photo(size: tuple[int, int], quality: int, orientation: int | None = None) -> bytes:
    noise = Image.effect_noise(size, 40).convert("RGB")
    base = Image.linear_gradient("L").resize(size).convert("RGB")
    img = Image.blend(base, noise, 0.35)
    buf = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(buf, "JPEG", quality=quality, exif=exif)
    else:
        img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def test_heavy_jpeg_that_fits_is_recompressed() -> None:
    body = _photo((1200, 800), quality=97)
    out = _resize_image(body, "image/jpeg", PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY)
    assert out is not None and len(out) < len(body) * 0.8
    assert Image.open(io.BytesIO(out)).size == (1200, 800)


def test_already_light_jpeg_is_kept_as_uploaded() -> None:
    body = _photo((600, 400), quality=40)
    assert _resize_image(body, "image/jpeg", PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY) == body


def test_large_photo_is_fitted_into_the_limit() -> None:
    body = _photo((2400, 1600), quality=90)
    out = _resize_image(body, "image/jpeg", PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY)
    assert Image.open(io.BytesIO(out)).size == (1600, 1066)


def test_phone_rotation_is_applied_not_lost() -> None:
    # Ориентация 6 — снято «боком», показывать повёрнутым на 90°.
    body = _photo((800, 600), quality=40, orientation=6)
    out = _resize_image(body, "image/jpeg", PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY)
    assert out != body
    assert Image.open(io.BytesIO(out)).size == (600, 800)


def test_backfill_takes_only_files_that_get_lighter() -> None:
    heavy = _photo((1200, 800), quality=97)
    plan = plan_one(17, "arenas/1/x_hero.jpg", heavy)
    assert plan is not None and len(plan.new_body) < plan.old_size
    assert plan_one(18, "arenas/1/y_hero.jpg", _photo((1200, 800), quality=60)) is None
