"""SEO-сниппеты: живое расписание не попадает в сниппет, текст не слипается, один бренд, старые URL ведут на /c/."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.city_hub_page import city_hub_search_description
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city

_GLUED = re.compile(r"\d[А-Яа-яЁё]|[а-яё]\d|[а-яё][А-ЯЁ]")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _text(fragment: str) -> str:
    """Текстовая версия, как её собирает краулер: теги выброшены, пробелы между узлами остаются."""
    return re.sub(r"<[^>]+>", "", fragment).replace(" ", " ")


def _hub(by_arena: dict[int, int]) -> dict:
    return {
        "city": {"id": 1, "name": "Минск"},
        "places": [
            {"id": 3, "name": "ТЦ Замок", "venue_type": "ice"},
            {"id": 1, "name": "Чижовка-арена", "venue_type": "ice"},
            {"id": 2, "name": "Каток Три", "venue_type": "ice"},
        ],
        "skate_by_arena": by_arena,
        "skate_counts": {"today": sum(by_arena.values())},
    }


def test_city_description_is_stable_and_free_of_today_tomorrow() -> None:
    quiet = city_hub_search_description(_hub({}))
    busy = city_hub_search_description(_hub({1: 9, 2: 7, 3: 1}))
    assert quiet == busy, "порядок и текст не зависят от сеансов сегодня"
    lowered = busy.lower()
    assert "сегодня" not in lowered and "завтра" not in lowered
    assert busy.startswith("Массовое катание в Минске: расписание сеансов, цены и адреса")


@pytest.mark.asyncio
async def test_city_page_marks_live_blocks_and_separates_day_chips(app_use_test_db, db_session) -> None:
    name = f"Снипетск {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    tomorrow = datetime.now(ZoneInfo("Europe/Minsk")).date() + timedelta(days=1)
    # Два катка — обычный хаб города (у одного катка страница другая: расписание катка внутри).
    for n in range(2):
        rink = await _insert_arena(db_session, city_id, name=f"Каток {n}{uuid.uuid4().hex[:4]}")
        await create_ice_session(
            db_session, rink, local_date=tomorrow, starts_at_local=f"1{n}:00", duration_minutes=60,
            kind="public_skate", price_adult_minor=1200,
        )
    await db_session.commit()
    invalidate_public_city_cache()
    async with _client() as client:
        resp = await client.get(f"/c/{city_slug(name)}")
    assert resp.status_code == 200
    html = resp.text
    # Живое расписание и счётчики — вне сниппета.
    assert "class=\"b-sec b-sec--when\" data-nosnippet" in html
    assert '<p class="b-hero__sub"><span data-nosnippet>' in html
    # В листе дней и в полосе «Когда» текст не слипается.
    sheet = html[html.index('class="b-days-sheet"'): html.index('class="b-days-sheet__grid"')]
    assert "data-nosnippet" in sheet
    grid = html[html.index('class="b-days-sheet__grid"'):]
    grid = grid[: grid.index("</div></div>")]
    assert not _GLUED.search(_text(grid)), _text(grid)[:200]
    nav = html[html.index('class="b-when vt-when-strip"'):]
    nav = nav[: nav.index("</nav>")]
    assert "СегодняЗавтра" not in _text(nav)
    # Бренд один: «Glideclub».
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    assert title.endswith("| Glideclub")
    assert '<meta property="og:site_name" content="Glideclub" />' in html


@pytest.mark.asyncio
async def test_legacy_city_path_redirects_to_c_and_unknown_stays_404(app_use_test_db, db_session) -> None:
    name = f"Легасисветск {uuid.uuid4().hex[:6]}"
    await _insert_city(db_session, name=name)
    await db_session.commit()
    invalidate_public_city_cache()
    slug = city_slug(name)
    async with _client() as client:
        moved = await client.get(f"/{slug}?w=today", follow_redirects=False)
        head = await client.head(f"/{slug}", follow_redirects=False)
        gone = await client.get("/net-takogo-mesta-zzz", headers={"accept": "text/html"})
        api = await client.get("/api/net-takogo-mesta")
    assert moved.status_code == 301 and moved.headers["location"] == f"/c/{slug}?w=today"
    assert head.status_code == 301
    assert gone.status_code == 404
    assert api.status_code == 404


@pytest.mark.asyncio
async def test_single_rink_city_page_keeps_schedule_out_of_snippet(app_use_test_db, db_session) -> None:
    name = f"Однокаток {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    rink = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
    tomorrow = datetime.now(ZoneInfo("Europe/Minsk")).date() + timedelta(days=1)
    await create_ice_session(
        db_session, rink, local_date=tomorrow, starts_at_local="12:00", duration_minutes=60,
        kind="public_skate", price_adult_minor=1200,
    )
    await db_session.commit()
    invalidate_public_city_cache()
    async with _client() as client:
        resp = await client.get(f"/c/{city_slug(name)}")
    assert resp.status_code == 200
    assert 'id="schedule" data-nosnippet' in resp.text
    assert '<p class="b-hero__sub"><span data-nosnippet>' in resp.text
