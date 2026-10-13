"""TASK-180/243: свежесть расписания считается, но публичные поверхности на неё не реагируют.

Решение владельца 2026-10-13 (TASK-243): «очень старое» расписание (> 72 ч) не прячем
и не пишем «Расписание не подтверждено» — сеансы показываем как обычно, без пометок.

Три катка одного города с прогонами парсера 1 ч, 7 ч и 80 ч назад плюс каток с ручными
сеансами (без парсера, сеансы «наблюдались» неделю назад). Часы фиксированы: всё
считается от одного ``NOW``, который явно передаётся в загрузчики страниц.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.application.arena_public_use_cases import get_hub_ice_teaser, list_public_ice_arenas
from src.application.catalog_home_page import load_catalog_home_view
from src.application.city_hub_page import load_city_hub_view, render_city_hub_page
from src.application.ice_city_day import get_city_ice_day
from src.application.ice_city_day_og import og_footer
from src.application.ice_city_day_page import render_ice_city_day_page
from src.application.place_card_image import card_lines
from src.application.place_page import load_place_view, render_place_page
from src.application import schedule_staleness
from src.application.schedule_staleness import (
    LEVEL_VERY_STALE,
    checked_at_label,
    stale_note,
    staleness_level,
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
    very = {
        "schedule_stale": True,
        "schedule_very_stale": True,
        "schedule_observed_at": datetime(2026, 10, 2, 12, 0, tzinfo=MINSK).isoformat(),
    }
    # Уровень по-прежнему считается (данные, алерты), слов для UI у него нет.
    assert staleness_level(very) == LEVEL_VERY_STALE
    assert stale_note(very, now=now) == ""
    assert not hasattr(schedule_staleness, "very_stale_note")
    assert not hasattr(schedule_staleness, "UNCONFIRMED_HEADING")
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


_FORBIDDEN = ("не подтвержд", "не обновлял", "уточн", "могло измениться")


def _assert_no_freshness_words(html: str) -> None:
    """Видимый текст страницы (без style/script) — без слов о свежести расписания."""
    visible = re.sub(r"<(style|script)\b.*?</\1>", " ", html, flags=re.S | re.I)
    low = visible.casefold()
    for bad in _FORBIDDEN:
        assert bad not in low, bad


@pytest.mark.asyncio
async def test_ice_city_day_shows_very_stale_like_any_other(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    day = await get_city_ice_day(
        db_session, city_id=ids["city"], on_date=date.today() + timedelta(days=2), now=now
    )
    by_id = {a["arena_id"]: a for a in day["arenas"]}

    # Все четыре катка в списке дня и в счёте; пометок нет.
    assert set(by_id) == {ids["fresh"], ids["stale"], ids["very"], ids["manual"]}
    assert day["session_count"] == 4
    assert all(a["stale_note"] == "" for a in by_id.values())
    # Флаг для внутреннего использования остаётся: 7 ч — stale (very — свой уровень).
    assert by_id[ids["stale"]]["stale"] is True
    assert "unconfirmed" not in day

    html = render_ice_city_day_page(
        city_name="Стейл", day=day, canonical_url="/ice/x/today", og_image_url="/og.png", cta_url=None
    )
    assert 'class="arena__stale"' not in html and 'class="unconfirmed' not in html
    _assert_no_freshness_words(html)
    assert "Каток Забытый" in html
    assert og_footer(day) == "Время и цены каждого сеанса — на странице"


@pytest.mark.asyncio
async def test_selection_page_keeps_very_stale_slots(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    city = {"id": ids["city"], "name": "Стейл", "country": "BY"}
    view = await load_selection_view(db_session, city=city, venue=None, when=None, now=now)

    assert "unconfirmed_notes" not in view
    assert view["slots"].get(ids["very"])
    assert view["session_count"] == 4

    html = render_selection_page(
        view,
        canonical_url="/c/x",
        og_image_url="/c/x/og.png",
        cta_url=None,
        share={"share_url": "https://x/c/x", "share_text": "x", "share_body": "x"},
        city_page_url=None,
    )
    assert 'class="pick__stale"' not in html
    _assert_no_freshness_words(html)


@pytest.mark.asyncio
async def test_place_page_shows_very_stale_sessions(app_use_test_db, db_session) -> None:
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

    for key in ("fresh", "stale", "very", "manual"):
        view = await load_place_view(db_session, str(ids[key]), now=now)
        assert view is not None, key
        assert view["session_count"] == 1, key
        assert view["next_slot"] is not None, key
        assert view["schedule_note"] == "", key
        html = render(view)
        assert 'class="sched__stale"' not in html, key
        assert 'class="slot' in html, key
        _assert_no_freshness_words(html)
    very = await load_place_view(db_session, str(ids["very"]), now=now)
    assert very is not None and very["schedule_level"] == LEVEL_VERY_STALE
    assert card_lines(very, invite=False)["foot"] == "Расписание, цены и как добраться — по ссылке"


@pytest.mark.asyncio
async def test_place_page_focus_on_very_stale_session_is_found(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    sid = (
        await db_session.execute(
            text("SELECT id FROM ice_sessions WHERE arena_id = :a ORDER BY starts_at_utc LIMIT 1"),
            {"a": ids["very"]},
        )
    ).scalar_one()
    view = await load_place_view(db_session, str(ids["very"]), session_id=int(sid), now=now)
    assert view is not None
    assert view["focus"] is not None and int(view["focus"]["id"]) == int(sid)
    assert view["focus_missing"] is False


@pytest.mark.asyncio
async def test_hub_teaser_includes_very_stale(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)
    teaser = await get_hub_ice_teaser(db_session, city_id=ids["city"])
    assert teaser is not None
    by_arena = {s["arena_id"]: s for s in teaser["sessions"]}
    assert set(by_arena) == {ids["fresh"], ids["stale"], ids["very"], ids["manual"]}
    # Флаг — для внутреннего использования; UI на него не реагирует.
    assert by_arena[ids["very"]]["schedule_stale"] is True
    assert by_arena[ids["stale"]]["schedule_stale"] is True
    assert by_arena[ids["fresh"]]["schedule_stale"] is False
    assert by_arena[ids["manual"]]["schedule_stale"] is False


@pytest.mark.asyncio
async def test_city_day_today_with_only_very_stale_sessions_lists_them(
    app_use_test_db, db_session
) -> None:
    """Сегодня сеансы есть только у «забытого» катка — день сегодняшний, каток в списке.

    ``now`` — 06:00 по Минску того дня, где лежат сеансы, чтобы 13:00 был впереди.
    """
    target = date.today() + timedelta(days=2)
    now = datetime(target.year, target.month, target.day, 6, 0, tzinfo=MINSK).astimezone(timezone.utc)
    cid = await _insert_city(db_session, name=f"Стейл-{uuid.uuid4().hex[:6]}")
    very = await _insert_arena(db_session, cid, name="Каток Забытый", phone="+375 17 123-45-67")
    tomorrow_rink = await _insert_arena(db_session, cid, name="Каток Завтрашний")
    await _add_future_session(db_session, very, days_ahead=2, observed_at=now - timedelta(hours=80))
    await _job(db_session, very, last_ok_at=now - timedelta(hours=80))
    await _add_future_session(db_session, tomorrow_rink, days_ahead=3, observed_at=now)
    await db_session.flush()

    day = await get_city_ice_day(db_session, city_id=cid, now=now)

    assert day["local_date"] == target.isoformat()
    assert day["is_today"] is True
    assert [a["arena_id"] for a in day["arenas"]] == [very]
    assert day["session_count"] == 1
    html = render_ice_city_day_page(
        city_name="Стейл", day=day, canonical_url="/ice/x/today", og_image_url="/og.png", cta_url=None
    )
    assert "Каток Забытый" in html and "Каток Завтрашний" not in html
    _assert_no_freshness_words(html)


@pytest.mark.asyncio
async def test_public_list_shows_very_stale_session(app_use_test_db, db_session) -> None:
    """Лента Mini App: у очень устаревшего катка обычный сеанс; свежесть — только в данных."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = await _city_with_arenas(db_session, now)

    res = await list_public_ice_arenas(db_session, city_id=ids["city"], intent="skate")
    by_id = {it["id"]: it for it in res["items"]}

    very = by_id[ids["very"]]
    assert very["freshness"]["schedule_very_stale"] is True
    assert very["live"]["kind"] == "session"
    assert very["live"].get("session_id") is not None
    assert str(very["live"].get("starts_at_local") or "")[:5]
    line = str(very.get("live_line") or "").casefold()
    assert "не подтвержд" not in line and "не обновлял" not in line
    for key in ("fresh", "stale", "manual"):
        assert by_id[ids[key]]["live"]["kind"] == "session"

    # Окно на день сеансов: забытый каток — такое же попадание, как остальные.
    day_iso = (date.today() + timedelta(days=2)).isoformat()
    windowed = await list_public_ice_arenas(
        db_session, city_id=ids["city"], intent="skate", day=day_iso
    )
    assert windowed["window"]["hits"] == 4


async def _only_very_stale_city(db_session, now: datetime) -> tuple[int, int, str]:
    name = f"Стейл-{uuid.uuid4().hex[:6]}"
    cid = await _insert_city(db_session, name=name)
    very = await _insert_arena(db_session, cid, name="Каток Забытый", phone="+375 17 123-45-67")
    await _add_future_session(db_session, very, days_ahead=2, observed_at=now - timedelta(hours=80))
    await _job(db_session, very, last_ok_at=now - timedelta(hours=80))
    await db_session.flush()
    return cid, very, name


@pytest.mark.asyncio
async def test_city_hub_counts_and_lists_very_stale_session(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cid, very, name = await _only_very_stale_city(db_session, now)

    view = await load_city_hub_view(db_session, city={"id": cid, "name": name, "country": "BY"}, now=now)
    assert view["skate_counts"]["all"] == 1
    assert view["skate_arena_count"] == 1
    assert [u.get("arena_name") for u in view["upcoming"]] == ["Каток Забытый"]

    html = render_city_hub_page(
        view,
        canonical_url="/c/x",
        og_image_url="/c/x/og.png",
        cta_url=None,
        share={"share_url": "https://x/c/x", "share_text": "x", "share_body": "x"},
    )
    assert "Каток Забытый" in html
    _assert_no_freshness_words(html)


@pytest.mark.asyncio
async def test_catalog_home_city_fact_includes_very_stale_session(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    cid, _very, _name = await _only_very_stale_city(db_session, now)
    from src.application.ice_city_day import invalidate_public_city_cache

    invalidate_public_city_cache()
    view = await load_catalog_home_view(db_session, now=now)
    invalidate_public_city_cache()
    city = next((c for c in view["cities"] if int(c["id"]) == cid), None)
    assert city is not None
    assert city["horizon_arenas_with_sessions"] == 1
    assert city["next_skate"] is not None
