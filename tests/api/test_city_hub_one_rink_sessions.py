"""City hub VARIANT_ONE: сеансы ведут на /p/...?s= для приглашения."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.application.city_hub_page import _b_one_today, _b_one_week, load_city_hub_view, render_city_hub_page
from src.application.ice_city_day import invalidate_public_city_cache
from tests.api.test_public_arenas import _minsk_today
from tests.api.test_schedule_staleness_surfaces import _only_very_stale_city
from tests.api.test_task224_city_hub import _session


def test_one_rink_week_and_today_html_link_sessions() -> None:
    today = date(2026, 10, 15)
    view = {
        "city": {"name": "Мозырь"},
        "today": today,
        "local_now": datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc),
        "week_rows": [
            {
                "id": 101,
                "local_date": today,
                "starts_at_local": "19:00:00",
                "ends_at_local": "19:45:00",
            },
            {
                "id": 102,
                "local_date": today + timedelta(days=1),
                "starts_at_local": "11:00:00",
                "ends_at_local": "11:45:00",
            },
            {
                "id": 103,
                "local_date": today + timedelta(days=1),
                "starts_at_local": "12:00:00",
                "ends_at_local": "12:45:00",
            },
        ],
    }
    rink = {"slug": "mozyr-global-ice", "id": 44, "amenities": {"skate_rental": True}}
    today_html = _b_one_today(view, rink)
    week_html = _b_one_week(view, rink)
    assert "?s=101" in today_html
    assert "?s=102" in week_html and "?s=103" in week_html
    assert "b-ticket--week" in week_html
    assert "каждые 1 ч" not in week_html


@pytest.mark.asyncio
async def test_one_rink_city_hub_render_includes_session_query(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cid, aid, name = await _only_very_stale_city(db_session, now)
    tomorrow = _minsk_today() + timedelta(days=1)
    sid = await _session(db_session, aid, day=tomorrow, hhmm="11:00")
    await db_session.flush()
    invalidate_public_city_cache()

    view = await load_city_hub_view(
        db_session,
        city={"id": cid, "name": name, "country": "BY"},
        now=now,
    )
    assert view["rink_count"] == 1
    assert view["variant"] == "one"

    html = render_city_hub_page(
        view,
        canonical_url="/c/x",
        og_image_url="/c/x/og.png",
        cta_url=None,
        share={"share_url": "https://x/c/x", "share_text": "x", "share_body": "x"},
    )
    assert f"?s={sid}" in html
    assert "data-glide-session-list-root" in html
    assert 'class="b-sched"' in html
    assert "b-ticket--week" not in html
