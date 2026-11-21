"""TASK-435: цены на хабе города — диапазоны за неделю и блок «Цены на массовое катание» (#ceny)."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.city_hub_page import (
    _b_minsk_rink_list,
    _tile_price_line,
    city_hub_document_title,
    load_city_hub_view,
    render_city_hub_page,
)
from src.application.ice_city_day import invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city, _minsk_today
from tests.api.test_schedule_staleness_surfaces import _job

_MINSK = ZoneInfo("Europe/Minsk")
_SHARE = {"share_url": "https://x/c/x", "share_text": "x", "share_body": "x"}


async def _skate(
    db_session,
    arena_id: int,
    *,
    day: date,
    hhmm: str,
    adult: int | None,
    child: int | None = None,
    rental: int | None = None,
    observed_at: datetime | None = None,
) -> None:
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=45,
        kind="public_skate",
        price_adult_minor=adult,
        price_child_minor=child,
        price_rental_minor=rental,
    )
    if observed_at is not None:
        await db_session.execute(
            text("UPDATE ice_sessions SET observed_at = :obs WHERE id = :id"),
            {"obs": observed_at, "id": int(created["id"])},
        )


async def _city(db_session, now: datetime) -> dict[str, int]:
    """Замок: 11/12 и 8/9, прокат 10, парсер свежий. Немига: 8,50/9, детского нет, ручное ≤ 3 дн.

    Тихий: цены есть, но парсер молчит 80 ч — штампа «Проверено» у него не было бы.
    Без цены: сеансы без цен — в таблицу не попадает.
    """
    cid = await _insert_city(db_session, name=f"Ценоград-{uuid.uuid4().hex[:6]}")
    ids = {
        "city": cid,
        "zamok": await _insert_arena(db_session, cid, name="ТЦ Замок"),
        "nemiga": await _insert_arena(db_session, cid, name="Каток на Немиге"),
        "quiet": await _insert_arena(db_session, cid, name="Каток Тихий"),
        "free": await _insert_arena(db_session, cid, name="Каток Без цены"),
    }
    d1 = _minsk_today() + timedelta(days=1)
    d2 = _minsk_today() + timedelta(days=2)
    fresh = now - timedelta(hours=1)
    await _skate(db_session, ids["zamok"], day=d1, hhmm="11:00", adult=1100, child=800, rental=1000, observed_at=fresh)
    await _skate(db_session, ids["zamok"], day=d1, hhmm="19:00", adult=1200, child=900, rental=1000, observed_at=fresh)
    await _skate(db_session, ids["zamok"], day=d2, hhmm="12:00", adult=1100, child=800, rental=1000, observed_at=fresh)
    await _job(db_session, ids["zamok"], last_ok_at=fresh)
    manual = now - timedelta(days=1)
    await _skate(db_session, ids["nemiga"], day=d1, hhmm="10:00", adult=850, observed_at=manual)
    await _skate(db_session, ids["nemiga"], day=d2, hhmm="10:00", adult=900, observed_at=manual)
    quiet = now - timedelta(hours=80)
    await _skate(db_session, ids["quiet"], day=d1, hhmm="10:00", adult=700, observed_at=quiet)
    await _job(db_session, ids["quiet"], last_ok_at=quiet)
    await _skate(db_session, ids["free"], day=d1, hhmm="10:00", adult=None, observed_at=fresh)
    await db_session.flush()
    invalidate_public_city_cache()
    return ids


def _render(view) -> str:
    return render_city_hub_page(view, canonical_url="/c/x", og_image_url="/c/x/og.png", cta_url=None, share=_SHARE)


@pytest.mark.asyncio
async def test_city_price_table_ranges_freshness_and_title(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city(db_session, now)
    city = {"id": ids["city"], "name": await _name(db_session, ids["city"]), "country": "BY"}
    view = await load_city_hub_view(db_session, city=city, now=now)

    table = view["price_table"]
    assert table is not None
    # AC-3/AC-8: без цены и с несвежими ценами — не строка таблицы; сортировка по названию.
    assert [r["name"] for r in table["rows"]] == ["Каток на Немиге", "ТЦ Замок"]
    # AC-4: «Проверено» — самая ранняя сверка среди строк (ручная Немига, день назад).
    manual_day = (now - timedelta(days=1)).astimezone(_MINSK).date()
    assert table["checked"] == f"{manual_day.day:02d}.{manual_day.month:02d}"

    html = _render(view)
    block = re.search(r'<section class="b-sec" id="ceny".*?</section>', html, re.S)
    assert block, "блок #ceny есть"
    sec = block.group(0)
    assert '<h2 class="b-h2" id="ceny-t">Цены на массовое катание</h2>' in sec
    assert f"<span>Проверено {table['checked']}</span>" in sec and "data-nosnippet" in sec
    # AC-1/AC-2: диапазоны недели; запятая в копейках.
    assert '<td data-k="Взрослый">11–12<span class="b-cost__u"> BYN</span></td>' in sec
    assert '<td data-k="Детский">8–9<span class="b-cost__u"> BYN</span></td>' in sec
    assert '<td data-k="Прокат">10<span class="b-cost__u"> BYN</span></td>' in sec
    assert '<td data-k="Взрослый">8,50–9<span class="b-cost__u"> BYN</span></td>' in sec
    # AC-3: нет цены — пустая клетка, не «0» и не «—».
    assert '<td data-k="Детский"></td><td data-k="Прокат"></td>' in sec
    assert "—" not in sec and ">0<" not in sec
    assert "Тихий" not in sec and "Без цены" not in sec
    assert 'class="b-cost__name" href="/p/' in sec
    # Ссылка в подзаголовке героя и место блока перед «Все места города».
    assert '<a href="#ceny">Цены</a>' in html
    # AC-5: «цены» в title, h1 прежний.
    assert "цены" in city_hub_document_title(view)
    assert re.search(r"<title>[^<]*цены[^<]*</title>", html)
    assert "Ценоград" in re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S).group(1)


@pytest.mark.asyncio
async def test_no_price_block_with_fewer_than_two_priced_arenas(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cid = await _insert_city(db_session, name=f"Одноценов-{uuid.uuid4().hex[:6]}")
    priced = await _insert_arena(db_session, cid, name="Каток Цена")
    other = await _insert_arena(db_session, cid, name="Каток Без")
    d1 = _minsk_today() + timedelta(days=1)
    await _skate(db_session, priced, day=d1, hhmm="10:00", adult=900, observed_at=now - timedelta(hours=2))
    await _skate(db_session, other, day=d1, hhmm="10:00", adult=None, observed_at=now - timedelta(hours=2))
    await db_session.flush()
    invalidate_public_city_cache()
    city = {"id": cid, "name": await _name(db_session, cid), "country": "BY"}
    view = await load_city_hub_view(db_session, city=city, now=now)
    assert view["price_table"] is None
    html = _render(view)
    assert 'id="ceny"' not in html and 'href="#ceny"' not in html
    assert "цены" not in city_hub_document_title(view)


def test_rink_list_and_tile_show_ranges_not_the_nearest_price() -> None:
    """AC-7: «Катки на ближайшие 7 дней» — цены недели; плитка «Лёд сегодня» — цены дня, 15,50 через запятую."""
    today = date(2026, 11, 21)
    tomorrow = today + timedelta(days=1)
    prices = {
        7: {
            "currency_code": "BYN",
            "days": {
                today: {"adult": (850, 900), "with_rental": (1500, 1550)},
                tomorrow: {"adult": (1200, 1200), "child": (900, 900), "with_rental": (2200, 2200)},
            },
        }
    }
    rink = {"id": 7, "slug": "zamok", "name": "ТЦ Замок", "address": "", "amenities": {}, "venue_type": "ice"}
    card = {
        "local_date": today,
        "starts_at_local": "17:30:00",
        "price_adult_minor": 850,
        "price_child_minor": None,
        "price_rental_minor": 650,
        "currency_code": "BYN",
    }
    view = {"city": {"name": "Минск"}, "today": today, "arena_prices": prices, "week_comparison": {7: card}}
    html = _b_minsk_rink_list(view, [rink]).replace(" ", " ")
    assert "взрослый 8,50–12 BYN · детский 9 BYN · взрослый с прокатом 15–22 BYN" in html
    line = _tile_price_line(view, card, rink).replace(" ", " ")
    assert line == "8,50–9 BYN · с прокатом 15–15,50 BYN"



async def _name(db_session, city_id: int) -> str:
    return str((await db_session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": city_id})).scalar())
