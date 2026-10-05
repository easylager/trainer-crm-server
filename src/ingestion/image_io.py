"""Safe PIL open for untrusted schedule images (decompression bomb guard)."""
from __future__ import annotations

import io

# ~5000×5000 RGB — enough for rink schedule photos, blocks huge bombs.
MAX_IMAGE_PIXELS = 25_000_000


def open_image_bytes(data: bytes):
    from PIL import Image

    prev = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        return Image.open(io.BytesIO(data))
    finally:
        Image.MAX_IMAGE_PIXELS = prev
