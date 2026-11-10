"""TASK-361: картинка лиги «Кто кого» — проверка загрузки и перекодирование (без базы)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.application import hockey_league_images as images
from src.application.hockey_league_images import LeagueImageError, prepare_image, thumb_key


def _encode(img: Image.Image, fmt: str, **kwargs) -> bytes:
    out = io.BytesIO()
    img.save(out, fmt, **kwargs)
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def test_big_jpeg_is_resized_to_1200_and_thumb_is_small() -> None:
    main, small = prepare_image(_encode(Image.new("RGB", (3000, 2000), (20, 120, 200)), "JPEG"))
    assert _open(main).format == "JPEG" and _open(small).format == "JPEG"
    assert _open(main).size == (1200, 800)
    assert max(_open(small).size) == 320


def test_small_image_is_not_upscaled() -> None:
    main, small = prepare_image(_encode(Image.new("RGB", (200, 100), (1, 2, 3)), "PNG"))
    assert _open(main).size == (200, 100)
    assert _open(small).size == (200, 100)


def test_exif_is_applied_then_dropped() -> None:
    """Телефонный снимок повёрнут тегом: поворот применяем, GPS и прочие метаданные не храним."""
    source = Image.new("RGB", (400, 200), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # повернуть на 90° по часовой
    exif[0x010F] = "Camera Vendor"
    exif.get_ifd(0x8825)[0x0002] = (53.0, 54.0, 0.0)  # GPS-широта
    main, small = prepare_image(_encode(source, "JPEG", exif=exif))
    assert _open(main).size == (200, 400)
    for blob in (main, small):
        assert len(_open(blob).getexif()) == 0
        assert b"Camera Vendor" not in blob and b"Exif" not in blob


def test_transparent_png_goes_onto_white_not_black() -> None:
    clear = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    main, _ = prepare_image(_encode(clear, "PNG"))
    r, g, b = _open(main).convert("RGB").getpixel((10, 10))
    assert min(r, g, b) > 240


def test_webp_is_accepted() -> None:
    main, _ = prepare_image(_encode(Image.new("RGB", (300, 300), (9, 99, 199)), "WEBP"))
    assert _open(main).format == "JPEG"


def test_payload_hidden_in_the_file_does_not_survive_reencoding() -> None:
    """«Полиглот»: настоящая картинка, к которой дописали скрипт или архив. В хранилище уйдёт чистый JPEG."""
    payload = b"<?php system($_GET['c']); ?>PK\x03\x04"
    polyglot = _encode(Image.new("RGB", (80, 80), (50, 60, 70)), "JPEG") + payload
    main, small = prepare_image(polyglot)
    assert payload not in main and payload not in small and b"<?php" not in main


@pytest.mark.parametrize(
    ("body", "code", "status"),
    [
        (b"", "empty", 400),
        (b"%PDF-1.7 not an image", "not_image", 400),
        (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "not_image", 400),
        (b"GIF89a" + b"\x00" * 40, "not_image", 400),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 30, "not_image", 400),
    ],
)
def test_garbage_is_rejected_with_a_human_message(body: bytes, code: str, status: int) -> None:
    with pytest.raises(LeagueImageError) as err:
        prepare_image(body)
    assert err.value.code == code and err.value.status == status
    assert str(err.value)


def test_gif_is_not_an_allowed_type() -> None:
    with pytest.raises(LeagueImageError) as err:
        prepare_image(_encode(Image.new("RGB", (20, 20), (1, 1, 1)), "GIF"))
    assert err.value.code == "unsupported" and err.value.status == 415


def test_truncated_jpeg_is_rejected() -> None:
    whole = _encode(Image.effect_noise((600, 600), 80).convert("RGB"), "JPEG")
    with pytest.raises(LeagueImageError) as err:
        prepare_image(whole[: len(whole) // 2])
    assert err.value.code == "not_image"


def test_file_over_five_megabytes_is_rejected_before_decoding() -> None:
    with pytest.raises(LeagueImageError) as err:
        prepare_image(b"\xff\xd8" + b"\x00" * images.MAX_UPLOAD_BYTES)
    assert err.value.code == "too_large" and err.value.status == 413


def test_pixel_bomb_is_rejected() -> None:
    """Файл в десятки килобайт, а в памяти — сотня миллионов пикселей."""
    bomb = _encode(Image.new("1", (10_000, 10_000)), "PNG", optimize=True)
    assert len(bomb) < images.MAX_UPLOAD_BYTES
    with pytest.raises(LeagueImageError) as err:
        prepare_image(bomb)
    assert err.value.code == "too_big_size" and err.value.status == 413


def test_thumb_key_sits_next_to_main() -> None:
    assert thumb_key("kk-leagues/7/abc.jpg") == "kk-leagues/7/abc_thumb.jpg"


def test_image_urls_are_public_and_none_without_image() -> None:
    assert images.image_urls(None) == (None, None)
    url, thumb = images.image_urls("kk-leagues/7/abc.jpg")
    assert url.endswith("/api/public/photos/kk-leagues/7/abc.jpg")
    assert thumb.endswith("/api/public/photos/kk-leagues/7/abc_thumb.jpg")
