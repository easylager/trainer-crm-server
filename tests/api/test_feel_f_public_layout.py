"""FEEL-F: публичный share без плашек свежести и с зарезервированным местом под контент."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.application.place_page import load_place_view, render_place_page
from src.application.selection_page import _place_html, load_selection_view, render_selection_page
from tests.api.test_schedule_staleness_surfaces import _city_with_arenas

ROOT = Path(__file__).resolve().parents[2]
STYLE_B = ROOT / "static" / "share" / "style-b.css"


def _visible_html(html: str) -> str:
    return re.sub(r"<(style|script)\b.*?</\1>", " ", html, flags=re.S | re.I)


def _assert_no_stale_schedule_markup(html: str) -> None:
    assert 'pick__stale' not in html
    assert 'sched__stale' not in html
    low = _visible_html(html).casefold()
    assert "обновлено" not in low


@pytest.mark.asyncio
async def test_selection_city_page_hides_stale_schedule_wording(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    city = {"id": ids["city"], "name": "Стейл", "country": "BY"}
    view = await load_selection_view(db_session, city=city, venue=None, when=None, now=now)
    html = render_selection_page(
        view,
        canonical_url="/c/x",
        og_image_url="/c/x/og.png",
        cta_url=None,
        share={"share_url": "https://x/c/x", "share_text": "x", "share_body": "x"},
        city_page_url=None,
    )
    _assert_no_stale_schedule_markup(html)


@pytest.mark.asyncio
async def test_place_page_hides_stale_schedule_wording_for_old_parser_run(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    for key in ("stale", "very"):
        view = await load_place_view(db_session, str(ids[key]), now=now)
        assert view is not None
        html = render_place_page(
            view,
            canonical_url="/p/x",
            base_path="/p/x",
            og_image_url="/p/x/og.png",
            story_image_url="/p/x/story.png",
            cta_url=None,
            city_page_url=None,
            share={"share_url": "https://x/p/x", "share_text": "x", "share_body": "x"},
        )
        _assert_no_stale_schedule_markup(html)


def test_style_b_reserves_map_and_carousel_height() -> None:
    css = STYLE_B.read_text(encoding="utf-8")
    assert re.search(r"\.home-map\s*\{[^}]*aspect-ratio:\s*600\s*/\s*520", css)
    assert re.search(r"\.b-scroll\s*\{[^}]*min-height:\s*188px", css)


def test_pick_photo_has_explicit_dimensions() -> None:
    html = _place_html(
        {
            "id": 1,
            "name": "Каток",
            "slug": "katok",
            "card": "/api/public/photos/arenas/1/x_card.jpg",
            "venue_type": "ice",
        },
        city_name="Минск",
        slots=[{"id": 9, "starts_at_local": "18:00", "local_date": datetime.now().date()}],
    )
    assert 'class="pick__photo"' in html
    assert 'width="88"' in html and 'height="72"' in html
