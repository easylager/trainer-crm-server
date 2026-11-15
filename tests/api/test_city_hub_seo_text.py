"""TASK-422: серверный текст хаба /c/minsk — расписание по каткам, цены, ответы; другие города не меняются."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from src.api.app import app
from src.application.city_hub_seo import SEO_RICH_HUB_CITIES, build_seo_model, seo_blocks_html
from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_session_use_cases import create_ice_session
from tests.api.test_public_arenas import _insert_arena, _insert_city

SCHEDULE_H2 = "Расписание массового катания в Минске по каткам"
PRICES_H2 = "Сколько стоит покататься в Минске"
FAQ_H2 = "Частые вопросы про катание в Минске"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Minsk")).date()


async def _session(db, arena_id, *, day, hhmm, kind="public_skate", minutes=60, adult=None, child=None, rental=None):
    await create_ice_session(
        db,
        arena_id,
        local_date=day,
        starts_at_local=hhmm,
        duration_minutes=minutes,
        kind=kind,
        price_adult_minor=adult,
        price_child_minor=child,
        price_rental_minor=rental,
    )
    await db.flush()


async def _minsk(db) -> int:
    return await _insert_city(db, name="Минск")


def _tomorrow() -> date:
    return _today() + timedelta(days=1)


async def _get(path: str) -> str:
    invalidate_public_city_cache()
    async with _client() as client:
        return (await client.get(path)).text


def test_only_minsk_is_listed() -> None:
    assert SEO_RICH_HUB_CITIES == {"minsk"}


@pytest.mark.asyncio
async def test_minsk_hub_has_server_blocks(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    cheap = await _insert_arena(db_session, cid, name="Дешёвый каток", address="пр. Победителей, 1")
    dear = await _insert_arena(db_session, cid, name="Дорогой каток")
    bare = await _insert_arena(db_session, cid, name="Каток без цен")
    d1, d2 = _tomorrow(), _tomorrow() + timedelta(days=1)
    for hh in ("10:00", "12:00", "08:30"):
        await _session(db_session, cheap, day=d1, hhmm=hh, minutes=45, adult=700, child=500, rental=300)
    await _session(db_session, cheap, day=d2, hhmm="11:00", minutes=45, adult=800, child=500, rental=300)
    await _session(db_session, dear, day=d1, hhmm="18:00", minutes=90, adult=1500, child=900)
    await _session(db_session, bare, day=d1, hhmm="20:00", minutes=45)
    await _session(db_session, dear, day=d1, hhmm="21:00", kind="hockey_practice", adult=2000)
    await db_session.commit()

    html = await _get("/c/minsk")
    assert f"<h2 class=\"b-h2\">{SCHEDULE_H2}</h2>" in html
    assert PRICES_H2 in html and FAQ_H2 in html
    sched = html.split(SCHEDULE_H2)[1].split(PRICES_H2)[0]
    # время — по возрастанию, без ведущего нуля у часа, через запятую
    assert "8:30, 10:00, 12:00" in sched
    assert "взрослый 7 BYN · детский 5 BYN" in sched.replace(" ", " ")
    assert re.search(r'<a href="/p/[^"]+/[^"]+" title="Расписание и цены: Дешёвый каток">Дешёвый каток</a>', sched)
    prices = html.split(PRICES_H2)[1].split(FAQ_H2)[0]
    assert prices.index("Дешёвый каток") < prices.index("Дорогой каток")
    assert "Каток без цен" not in prices  # ни одной цены - нет строки в таблице цен
    assert "Каток без цен" in sched  # но в расписании остаётся
    assert "пр. Победителей, 1" in prices
    assert prices.count("уточняйте у катка") == 1  # только прокат у «Дорогого»; у «Дешёвого» все три цены
    faq = html.split(FAQ_H2)[1]
    assert "Чаще всего — 45 минут" in faq and "от 45 до 90" in faq
    assert "Где в Минске взять коньки напрокат?" in faq and "Дешёвый каток" in faq
    assert "(ОХМ)" in faq
    # основной текст виден поисковику: ни одного data-nosnippet внутри блоков, нет FAQPage-разметки
    seo_text = html.split(SCHEDULE_H2)[1].split("Все места города")[0]
    assert "data-nosnippet" not in seo_text
    assert "FAQPage" not in html


@pytest.mark.asyncio
async def test_empty_day_falls_to_next_day_with_sessions(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    a = await _insert_arena(db_session, cid, name="Единственный каток")
    b = await _insert_arena(db_session, cid, name="Второй каток")
    far = _today() + timedelta(days=4)
    await _session(db_session, a, day=far, hhmm="10:00", adult=900)
    await _session(db_session, b, day=far, hhmm="11:00", adult=900)
    await db_session.commit()
    html = await _get("/c/minsk")
    sched = html.split(SCHEDULE_H2)[1].split(PRICES_H2)[0]
    assert "Сегодня" not in sched and "Завтра" not in sched
    assert sched.count('<h3 class="b-seo__h3">') == 1
    assert "10:00" in sched and "11:00" in sched


@pytest.mark.asyncio
async def test_minsk_without_sessions_has_no_blocks(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    await _insert_arena(db_session, cid, name="Каток 1")
    await _insert_arena(db_session, cid, name="Каток 2")
    await db_session.commit()
    html = await _get("/c/minsk")
    assert SCHEDULE_H2 not in html and PRICES_H2 not in html and FAQ_H2 not in html


@pytest.mark.asyncio
async def test_other_city_page_is_unchanged(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name="Молодечно")
    a = await _insert_arena(db_session, cid, name="Арена один")
    b = await _insert_arena(db_session, cid, name="Арена два")
    for arena in (a, b):
        await _session(db_session, arena, day=_tomorrow(), hhmm="10:00", adult=900, rental=300)
    await db_session.commit()
    html = await _get(f"/c/{city_slug('Молодечно')}")
    assert "b-seo" not in html
    assert "Частые вопросы про катание" not in html and "Расписание массового катания" not in html


def _row(arena_id, day, hh, **kw):
    h, m = hh.split(":")
    start = time(int(h), int(m))
    return {
        "arena_id": arena_id,
        "kind": kw.get("kind", "public_skate"),
        "local_date": day,
        "starts_at_local": start,
        "ends_at_local": time((int(h) + 1) % 24, int(m)),
        "price_adult_minor": kw.get("adult"),
        "price_child_minor": kw.get("child"),
        "price_rental_minor": kw.get("rental"),
        "currency_code": "BYN",
    }


def _view(places, model):
    return {
        "city": {"name": "Минск"},
        "slug": "minsk",
        "places": places,
        "seo_text": model,
        "skate_counts": {"weekend": 0},
        "skate_window_arena_counts": {},
    }


def test_many_times_are_cut_and_no_prices_means_no_price_line() -> None:
    day = date(2026, 11, 20)
    places = [{"id": 1, "name": "А", "slug": "a", "address": ""}, {"id": 2, "name": "Б", "slug": "b", "address": ""}]
    rows = [_row(1, day, f"{h}:00") for h in range(6, 21)]  # 15 сеансов
    rows.append(_row(2, day, "10:00"))
    model = build_seo_model(rows, places, today=day)
    html = seo_blocks_html(_view(places, model))
    assert "6:00, 7:00" in html and "19:00 и ещё 1" in html
    assert "b-seo__price" not in html  # цен нет нигде — строки цен нет
    assert "взять коньки напрокат" not in html  # прокат не указан — вопроса нет
    assert "открытые тренировки" not in html  # ОХМ нет — вопроса нет
    assert "расписание на выходные" not in html


def test_no_sessions_no_model_no_html() -> None:
    assert build_seo_model([], [{"id": 1, "name": "А", "slug": "a"}], today=date(2026, 11, 20)) is None
    assert seo_blocks_html(_view([], None)) == ""


@pytest.mark.asyncio
async def test_minsk_hub_sql_budget_does_not_grow_with_rinks(app_use_test_db, db_session) -> None:
    cid = await _minsk(db_session)
    ids = [await _insert_arena(db_session, cid, name=f"Каток {i}") for i in range(2)]
    for aid in ids:
        await _session(db_session, aid, day=_tomorrow(), hhmm="10:00", adult=900, rental=300)
    await db_session.commit()
    bind = db_session.sync_session.get_bind()
    counts = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):
        if (statement or "").lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            counts["n"] += 1

    event.listen(bind, "before_cursor_execute", _before)
    try:
        await _get("/c/minsk")
        small = counts["n"]
        for i in range(10):
            aid = await _insert_arena(db_session, cid, name=f"Новый {i}")
            await _session(db_session, aid, day=_tomorrow(), hhmm="11:00", adult=900, rental=300)
        await db_session.commit()
        counts["n"] = 0
        await _get("/c/minsk")
        big = counts["n"]
    finally:
        event.remove(bind, "before_cursor_execute", _before)
    assert abs(big - small) <= 1, (small, big)
