"""TASK-180: устаревшее расписание видно на SSR-поверхностях, очень устаревшее — не выдаётся за расписание.

Три катка одного города с прогонами парсера 1 ч, 7 ч и 80 ч назад плюс каток с ручными
сеансами (без парсера, сеансы «наблюдались» неделю назад). Часы фиксированы: всё
считается от одного ``NOW``, который явно передаётся в загрузчики страниц.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.arena_public_use_cases import get_hub_ice_teaser, list_public_ice_arenas
from src.application.ice_city_day import get_city_ice_day
from src.application.ice_city_day_og import og_footer
from src.application.ice_city_day_page import render_ice_city_day_page
from src.application.place_card_image import card_lines
from src.application.place_page import load_place_view, render_place_page
from src.application.schedule_staleness import (
    checked_at_label,
    stale_note,
    very_stale_note,
)
from src.application.selection_page import load_selection_view, render_selection_page
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city

MINSK = ZoneInfo("Europe/Minsk")


# ── Слова и даты (фиксированные часы, AC-3) ─────────────────────────────


def test_checked_label_uses_minsk_days_at_one_am() -> None:
    """01:00 по Минску = 22:00 UTC прошлых суток. «Сегодня»/«вчера» — по Минску, не по UTC."""
    now = datetime(2026, 10, 6, 1, 0, tzinfo=MINSK)
    # 00:20 по Минску того же дня (в UTC — ещё 5 октября).
    assert checked_at_label(datetime(2026, 10, 6, 0, 20, tzinfo=MINSK), now=now) == "сегодня в 00:20"
    # 23:50 по Минску вчера (в UTC — тоже 5 октября, как и «сейчас»).
    assert checked_at_label(datetime(2026, 10, 5, 23, 50, tzinfo=MINSK), now=now) == "вчера в 23:50"
    assert checked_at_label(datetime(2026, 10, 3, 18, 40, tzinfo=MINSK), now=now) == "3 окт в 18:40"


def test_notes_wording() -> None:
    now = datetime(2026, 10, 6, 9, 0, tzinfo=MINSK)
    stale = {
        "schedule_stale": True,
        "schedule_very_stale": False,
        "schedule_observed_at": datetime(2026, 10, 5, 18, 40, tzinfo=MINSK).isoformat(),
    }
    assert stale_note(stale, now=now) == ""
    assert very_stale_note(stale, now=now) == ""
    very = {
        "schedule_stale": True,
        "schedule_very_stale": True,
        "schedule_observed_at": datetime(2026, 10, 2, 12, 0, tzinfo=MINSK).isoformat(),
    }
    assert very_stale_note(very, now=now) == "Расписание не обновлялось 4 дня — уточните по телефону"
    assert (
        very_stale_note(very, now=now, has_phone=False, has_site=True)
        == "Расписание не обновлялось 4 дня — уточните на сайте катка"
    )
    assert stale_note(very, now=now) == ""
    assert stale_note({"schedule_stale": False}, now=now) == ""


# ── SSR-страницы на реальной БД ──────────────────────────────────────────


async def _job(db_session, arena_id: int, *, last_ok_at: datetime) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at,
                                         config, created_at, last_ok_at)
            VALUES (:aid, 'stale180_v1', true, 'daily', now(), '{}'::jsonb,
                    now() - interval '30 days', :ok)
            """
        ),
        {"aid": arena_id, "ok": last_ok_at},
    )


async def _city_with_arenas(db_session, now: datetime) -> dict[str, int]:
    cid = await _insert_city(db_session, name=f"Стейл-{uuid.uuid4().hex[:6]}")
    ids = {
        "city": cid,
        "fresh": await _insert_arena(db_session, cid, name="Каток Свежий"),
        "stale": await _insert_arena(db_session, cid, name="Каток Вчерашний"),
        "very": await _insert_arena(db_session, cid, name="Каток Забытый", phone="+375 17 123-45-67"),
        "manual": await _insert_arena(db_session, cid, name="Каток Ручной"),
    }
    runs = {"fresh": timedelta(hours=1), "stale": timedelta(hours=7), "very": timedelta(hours=80)}
    for key, ago in runs.items():
        # observed_at сеанса = момент прогона, иначе свежий observed_at сам «подтвердит» расписание.
        await _add_future_session(db_session, ids[key], days_ahead=2, observed_at=now - ago)
        await _job(db_session, ids[key], last_ok_at=now - ago)
    await _add_future_session(db_session, ids["manual"], days_ahead=2, observed_at=now - timedelta(days=7))
    await db_session.flush()
    return ids


@pytest.mark.asyncio
async def test_ice_city_day_marks_stale_and_drops_very_stale(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    day = await get_city_ice_day(
        db_session, city_id=ids["city"], on_date=date.today() + timedelta(days=2), now=now
    )
    by_id = {a["arena_id"]: a for a in day["arenas"]}

    # AC-1: 7 ч — помечен; 1 ч и ручной — нет.
    assert by_id[ids["stale"]]["stale_note"] == ""
    assert by_id[ids["fresh"]]["stale_note"] == ""
    assert by_id[ids["manual"]]["stale_note"] == ""
    assert day["stale_arena_count"] == 1
    # AC-2: 80 ч — не в списке дня и не в счёте сеансов, а в «не подтверждено».
    assert ids["very"] not in by_id
    assert day["session_count"] == 3
    assert [u["arena_id"] for u in day["unconfirmed"]] == [ids["very"]]
    # 80 ч — это 3 или 4 календарных дня по Минску, в зависимости от часа запуска.
    days = (now.astimezone(MINSK).date() - (now - timedelta(hours=80)).astimezone(MINSK).date()).days
    assert day["unconfirmed"][0]["note"] == f"Расписание не обновлялось {days} дня — уточните по телефону"

    html = render_ice_city_day_page(
        city_name="Стейл", day=day, canonical_url="/ice/x/today", og_image_url="/og.png", cta_url=None
    )
    assert 'class="arena__stale"' not in html and "могло измениться" not in html
    assert "Расписание не подтверждено" in html and "Каток Забытый" in html
    assert 'href="tel:+375171234567"' in html
    # Каток Забытый — только в блоке «не подтверждено», без своего списка сеансов.
    assert html.count("Каток Забытый") == 1
    assert og_footer(day) == "Время и цены каждого сеанса — на странице"


@pytest.mark.asyncio
async def test_selection_page_marks_stale_and_hides_very_stale_slots(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    city = {"id": ids["city"], "name": "Стейл", "country": "BY"}
    view = await load_selection_view(db_session, city=city, venue=None, when=None, now=now)

    assert set(view["stale_notes"]) == {ids["stale"]}
    assert set(view["unconfirmed_notes"]) == {ids["very"]}
    assert ids["very"] not in view["slots"]
    assert view["session_count"] == 3

    html = render_selection_page(
        view,
        canonical_url="/c/x",
        og_image_url="/c/x/og.png",
        cta_url=None,
        share={"share_url": "https://x/c/x", "share_text": "x", "share_body": "x"},
        city_page_url=None,
    )
    assert html.count('class="pick__stale"') == 1
    assert "могло измениться" not in html
    assert "Расписание не обновлялось" in html and "уточните по телефону" in html


@pytest.mark.asyncio
async def test_place_page_stale_and_very_stale(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)

    def render(view) -> str:
        return render_place_page(
            view,
            canonical_url="/p/x",
            base_path="/p/x",
            og_image_url="/p/x/og.png",
            story_image_url="/p/x/story.png",
            cta_url=None,
            city_page_url=None,
            share={"share_url": "https://x/p/x", "share_text": "x", "share_body": "x"},
        )

    stale = await load_place_view(db_session, str(ids["stale"]), now=now)
    assert stale is not None and stale["session_count"] == 1
    assert stale["schedule_note"] == ""
    assert 'class="sched__stale"' not in render(stale)
    assert card_lines(stale, invite=False)["foot"] == "Расписание, цены и как добраться — по ссылке"

    very = await load_place_view(db_session, str(ids["very"]), now=now)
    assert very is not None
    assert very["days"] == [] and very["next_slot"] is None and very["session_count"] == 0
    assert very["schedule_note"].startswith("Расписание не обновлялось ")
    html = render(very)
    assert "Расписание не обновлялось" in html and 'href="tel:+375171234567"' in html
    assert 'class="slot' not in html

    for key in ("fresh", "manual"):
        view = await load_place_view(db_session, str(ids[key]), now=now)
        assert view is not None and view["schedule_note"] == "" and view["session_count"] == 1
        assert 'class="sched__stale"' not in render(view)


@pytest.mark.asyncio
async def test_hub_teaser_skips_very_stale_and_flags_stale(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    teaser = await get_hub_ice_teaser(db_session, city_id=ids["city"])
    assert teaser is not None
    by_arena = {s["arena_id"]: s for s in teaser["sessions"]}
    assert ids["very"] not in by_arena
    assert by_arena[ids["stale"]]["schedule_stale"] is True
    assert by_arena[ids["fresh"]]["schedule_stale"] is False
    assert by_arena[ids["manual"]]["schedule_stale"] is False


@pytest.mark.asyncio
async def test_city_day_keeps_today_when_all_today_arenas_are_very_stale(
    app_use_test_db, db_session
) -> None:
    """Сегодня сеансы есть только у «забытого» катка — день не уезжает на завтра.

    Иначе пропадал бы и список «Расписание не подтверждено» на сегодня.
    ``now`` — 06:00 по Минску того дня, где лежат сеансы, чтобы 13:00 был впереди.
    """
    target = date.today() + timedelta(days=2)
    now = datetime(target.year, target.month, target.day, 6, 0, tzinfo=MINSK).astimezone(timezone.utc)
    cid = await _insert_city(db_session, name=f"Стейл-{uuid.uuid4().hex[:6]}")
    very = await _insert_arena(db_session, cid, name="Каток Забытый", phone="+375 17 123-45-67")
    tomorrow_rink = await _insert_arena(db_session, cid, name="Каток Завтрашний")
    await _add_future_session(db_session, very, days_ahead=2, observed_at=now - timedelta(hours=80))
    await _job(db_session, very, last_ok_at=now - timedelta(hours=80))
    # Завтра есть свежий сеанс — раньше страница уезжала бы на него.
    await _add_future_session(db_session, tomorrow_rink, days_ahead=3, observed_at=now)
    await db_session.flush()

    day = await get_city_ice_day(db_session, city_id=cid, now=now)

    assert day["local_date"] == target.isoformat()
    assert day["is_today"] is True
    assert day["arenas"] == [] and day["session_count"] == 0
    assert [u["arena_id"] for u in day["unconfirmed"]] == [very]
    html = render_ice_city_day_page(
        city_name="Стейл", day=day, canonical_url="/ice/x/today", og_image_url="/og.png", cta_url=None
    )
    assert "Расписание не подтверждено" in html and "Каток Забытый" in html
    assert "Каток Завтрашний" not in html


@pytest.mark.asyncio
async def test_public_list_does_not_advertise_very_stale_session(app_use_test_db, db_session) -> None:
    """Лента Mini App: у очень устаревшего катка нет дня/времени/цены — только «уточните»."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)

    res = await list_public_ice_arenas(db_session, city_id=ids["city"], intent="skate")
    by_id = {it["id"]: it for it in res["items"]}

    very = by_id[ids["very"]]
    assert very["freshness"]["schedule_very_stale"] is True
    assert very["live"]["kind"] == "unconfirmed"
    assert "starts_at_local" not in very["live"] and "session_id" not in very["live"]
    days = (now.astimezone(MINSK).date() - (now - timedelta(hours=80)).astimezone(MINSK).date()).days
    assert very["live"]["text"] == f"Расписание не обновлялось {days} дня — уточните по телефону"
    assert very["live_line"] == very["live"]["text"]
    for key in ("fresh", "stale", "manual"):
        assert by_id[ids[key]]["live"]["kind"] == "session"

    # Окно на день сеансов: забытый каток не считается попаданием в окно.
    day_iso = (date.today() + timedelta(days=2)).isoformat()
    windowed = await list_public_ice_arenas(
        db_session, city_id=ids["city"], intent="skate", day=day_iso
    )
    assert windowed["window"]["hits"] == 3
    assert windowed["items"][-1]["id"] == ids["very"]
