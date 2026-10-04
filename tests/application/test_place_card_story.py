"""TASK-168: story.png — QR и короткий путь на корешке билета."""

import io
from datetime import date, datetime, timezone

from PIL import Image

from src.application.place_card_image import (
    _story_qr_image,
    render_place_card,
    share_display_path,
)


def test_share_display_path_strips_host() -> None:
    assert share_display_path("https://glide.example/c/minsk?w=weekend") == "/c/minsk?w=weekend"
    assert share_display_path("https://x/p/minsk/arena") == "/p/minsk/arena"


def test_story_qr_roundtrip_payload() -> None:
    url = "https://example.com/c/minsk"
    qr = _story_qr_image(url, 120)
    assert qr is not None
    assert qr.size == (120, 120)


def test_story_png_renders_with_qr_region() -> None:
    view = {
        "card": {
            "venue_type": "ice",
            "name": "ТЦ Замок",
            "city_name": "Минск",
            "venue_noun": "каток",
        },
        "today": date(2026, 10, 5),
        "now": datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        "session_count": 3,
    }
    png = render_place_card(
        view,
        story=True,
        share_url="https://glide.example/c/minsk",
        display_path="/c/minsk",
    )
    img = Image.open(io.BytesIO(png))
    assert img.size == (1080, 1920)
    # QR — светлый блок в правом нижнем углу билета (не весь градиент).
    corner = img.crop((780, 1320, 980, 1520)).convert("L")
    assert max(corner.get_flattened_data()) > 200
