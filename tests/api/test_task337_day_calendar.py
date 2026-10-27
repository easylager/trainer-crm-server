"""TASK-337: календарь дня на главной и в хабе города, ``?w=YYYY-MM-DD``."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.application.ice_city_day import city_slug, invalidate_public_city_cache
from src.application.ice_time_windows import is_hub_day_key, parse_hub_window, resolve_hub_window
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_task224_city_hub import _client, _minsk_today, _session

_NOW = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)  # вторник


def test_parse_hub_window_grammar():
    assert parse_hub_window("weekend", _NOW) == "weekend"
    assert parse_hub_window("2026-10-31", _NOW) == "2026-10-31"
    assert parse_hub_window("2026-10-27", _NOW) == "today"  # сегодня и завтра сводятся к своим ключам
    assert parse_hub_window("2026-10-28", _NOW) == "tomorrow"
    assert parse_hub_window("2026-11-02", _NOW) == "2026-11-02"  # последний день пикера
    assert parse_hub_window("2026-11-03", _NOW) is None  # за неделей
    assert parse_hub_window("2026-10-26", _NOW) is None  # прошедший
    assert parse_hub_window("2026-02-31", _NOW) is None  # такой даты нет
    assert parse_hub_window("sat", _NOW) is None and parse_hub_window(None, _NOW) is None


def test_resolve_hub_window_for_a_day():
    window = resolve_hub_window("2026-10-31", _NOW)
    assert window is not None and window.key == "day" and window.local_date == "2026-10-31"
    assert is_hub_day_key("2026-10-31") and not is_hub_day_key("weekend")
    assert resolve_hub_window("tomorrow", _NOW).key == "tomorrow"


async def _city_with_rinks(db_session, *, rinks: int = 2, day_offset: int = 3, per_rink: int = 2):
    name = f"Календарьград {uuid.uuid4().hex[:6]}"
    city_id = await _insert_city(db_session, name=name)
    target = _minsk_today() + timedelta(days=day_offset)
    for _ in range(rinks):
        rink = await _insert_arena(db_session, city_id, name=f"Каток {uuid.uuid4().hex[:4]}")
        for hhmm in ("12:00", "14:00")[:per_rink]:
            await _session(db_session, rink, day=target, hhmm=hhmm)
    await db_session.commit()
    invalidate_public_city_cache()
    return name, city_slug(name), target


@pytest.mark.asyncio
async def test_hub_opens_in_a_chosen_day(app_use_test_db, db_session) -> None:
    name, slug, target = await _city_with_rinks(db_session)
    async with _client() as client:
        response = await client.get(f"/c/{slug}", params={"w": target.isoformat()})
    html = response.text
    assert response.status_code == 200
    assert 'name="robots" content="noindex, follow"' in html  # день — вариант страницы, не отдельный адрес
    assert 'class="b-cal b-cal--day"' in html and 'aria-current="true"' in html
    strip = re.search(r'<nav class="b-when.*?</nav>', html, re.S).group(0)
    assert 'aria-current="true"' not in strip, "в полосе ничего не активно: выбран день, а не окно"
    assert "4 сеанса" in html.replace(" ", " ")
    # лист: выбранный день отмечен и показывает число сеансов города
    chip = re.search(rf'<a class="b-dayc[^"]*" href="/c/{slug}\?w={target.isoformat()}" aria-current="true">(.*?)</a>', html, re.S)
    assert chip and "<small>4</small>" in chip.group(1)


@pytest.mark.asyncio
async def test_hub_day_matches_window_keys_and_old_links(app_use_test_db, db_session) -> None:
    name, slug, target = await _city_with_rinks(db_session)
    today = _minsk_today()
    async with _client() as client:
        as_date = await client.get(f"/c/{slug}", params={"w": today.isoformat()})
        as_key = await client.get(f"/c/{slug}", params={"w": "today"})
        far = await client.get(f"/c/{slug}", params={"w": (today + timedelta(days=9)).isoformat()})
        weekend = await client.get(f"/c/{slug}", params={"w": "weekend"})
    key_strip = re.search(r'<nav class="b-when.*?</nav>', as_key.text, re.S).group(0)
    date_strip = re.search(r'<nav class="b-when.*?</nav>', as_date.text, re.S).group(0)
    assert key_strip == date_strip, "дата «сегодня» = окно «сегодня»"
    assert 'class="b-cal b-cal--day"' not in as_date.text
    assert 'class="b-cal b-cal--day"' not in far.text, "дата вне недели не выбирает день"
    assert weekend.status_code == 200 and 'class="b-cal"' in weekend.text


@pytest.mark.asyncio
async def test_home_day_selected_and_links_carry_it(app_use_test_db, db_session) -> None:
    name, slug, target = await _city_with_rinks(db_session)
    async with _client() as client:
        chosen = await client.get("/", params={"when": "day", "d": target.isoformat()}, cookies={"glide_city": slug})
        plain = await client.get("/", cookies={"glide_city": slug})
    html = chosen.text
    assert 'class="b-cal b-cal--day"' in html
    strip = re.search(r'<nav class="b-when.*?</nav>', html, re.S).group(0)
    assert 'aria-current="true"' not in strip
    assert f'class="b-city" href="/c/{slug}?w={target.isoformat()}"' in html, "выбранный день едет в город"
    assert 'class="b-cal"' in plain.text and 'class="b-cal b-cal--day"' not in plain.text
    assert f'href="/?when=day&amp;d={target.isoformat()}"' in plain.text or f'href="/?when=day&d={target.isoformat()}"' in plain.text
    tomorrow = _minsk_today() + timedelta(days=1)
    assert 'href="/?when=tomorrow"' in plain.text and f"d={tomorrow.isoformat()}" not in plain.text


@pytest.mark.asyncio
async def test_single_rink_city_has_no_calendar_but_opens_on_the_day(app_use_test_db, db_session) -> None:
    name, slug, target = await _city_with_rinks(db_session, rinks=1)
    async with _client() as client:
        response = await client.get(f"/c/{slug}", params={"w": target.isoformat()})
    assert response.status_code == 200
    assert 'class="b-cal' not in response.text, "в городе с одним катком дни уже на виду, календарь не нужен"


@pytest.mark.asyncio
async def test_empty_day_stays_selected_and_points_to_the_nearest_day(app_use_test_db, db_session) -> None:
    name, slug, target = await _city_with_rinks(db_session, day_offset=4)
    empty_day = _minsk_today() + timedelta(days=3)
    async with _client() as client:
        response = await client.get(f"/c/{slug}", params={"w": empty_day.isoformat()})
    html = response.text.replace("\u00a0", " ")
    assert response.status_code == 200 and 'class="b-cal b-cal--day"' in html
    assert "сеансов нет" in html
    assert f'href="/c/{slug}?w={target.isoformat()}"' in html and "Ближайший день с сеансами" in html


def test_parse_hub_window_any():
    assert parse_hub_window("any", _NOW) == "any"
    from src.application.ice_time_windows import resolve_home_window

    key, window, picker = resolve_home_window("any", None, _NOW)
    assert key == "any" and picker is False and window.label == "Любой день"
    assert window.ends_at == datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)  # конец 2 ноября по Минску


@pytest.mark.asyncio
async def test_any_day_on_home_and_in_hub(app_use_test_db, db_session) -> None:
    name, slug, target = await _city_with_rinks(db_session)  # 4 сеанса в один из дней недели
    async with _client() as client:
        home = await client.get("/", params={"when": "any"}, cookies={"glide_city": slug})
        hub = await client.get(f"/c/{slug}", params={"w": "any"})
        default_hub = await client.get(f"/c/{slug}")
    # главная: плитка «ВСЕ / 7 дн», в полосе ничего не активно, город ведёт в хаб «любой день»
    assert 'class="b-cal__date b-cal__date--any"' in home.text
    strip = re.search(r'<nav class="b-when.*?</nav>', home.text, re.S).group(0)
    assert 'aria-current="true"' not in strip
    assert f'class="b-city" href="/c/{slug}?w=any"' in home.text
    assert "На этой неделе" in home.text
    # лист: первая строка «Любой день» с суммой сеансов, отмечена
    row = re.search(r'<a class="b-dayc b-dayc--any" href="/\?when=any" aria-current="true">(.*?)</a>', home.text, re.S)
    assert row and "Любой день" in row.group(1) and "ближайшие 7 дней" in row.group(1)
    # хаб: тот же режим, noindex, строка отмечена, день не выбран
    assert hub.status_code == 200
    assert 'name="robots" content="noindex, follow"' in hub.text
    assert f'class="b-dayc b-dayc--any" href="/c/{slug}?w=any" aria-current="true"' in hub.text
    assert 'b-cal__date--any' in hub.text
    # голый хаб остаётся индексируемым, «любой день» в нём не отмечен
    assert 'name="robots" content="index, follow"' in default_hub.text
    assert 'b-dayc--any" href="/c/' in default_hub.text and 'b-cal__date--any' not in default_hub.text
