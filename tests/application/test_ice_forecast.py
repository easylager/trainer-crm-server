"""TASK-294: прогноз «Лёд на выходные» и старт сезона."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_forecast import (
    ALL_SESSIONS_LABEL,
    OPT_OUT_CALLBACK,
    OPT_OUT_LABEL,
    SEASON_START_TEXT,
    SaleSlot,
    TicketArena,
    build_forecast_markup,
    button_label,
    campaign_key_for,
    fetch_forecast_audience,
    ice_forecast_due,
    levels_for_day,
    list_ticket_arenas,
    live_line_from_slots,
    load_sale_slots,
    markup_without_optout,
    record_ice_forecast_optout,
    render_forecast,
    ru_tickets,
    send_ice_forecast,
    weekend_for,
)
from src.application.session_load import (
    LEVEL_BUSY,
    LEVEL_CALM,
    LEVEL_MEDIUM,
    LoadRule,
    invalidate_session_load_cache,
    load_session_load_context,
)
from src.shared.config import Settings
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

MINSK = ZoneInfo("Europe/Minsk")
_SAT = date(2026, 12, 5)
_SUN = date(2026, 12, 6)


def _rule(day_group: str, start: time, end: time | None, level: str, rule_id: int) -> LoadRule:
    return LoadRule(
        id=rule_id,
        scope="all",
        character=None,
        arena_id=None,
        day_group=day_group,
        starts_from=start,
        starts_before=end,
        level=level,
        source="default",
    )


def _default_rules() -> tuple[LoadRule, ...]:
    bands = [
        ("mon_thu", [(time(0, 0), time(16, 0), "calm"), (time(16, 0), time(19, 0), "medium"), (time(19, 0), None, "busy")]),
        ("fri", [(time(0, 0), time(15, 0), "calm"), (time(15, 0), time(18, 0), "medium"), (time(18, 0), None, "busy")]),
        ("sat", [(time(0, 0), time(11, 0), "medium"), (time(11, 0), time(20, 0), "busy"), (time(20, 0), None, "medium")]),
        (
            "sun",
            [
                (time(0, 0), time(11, 0), "medium"),
                (time(11, 0), time(16, 0), "busy"),
                (time(16, 0), time(19, 0), "medium"),
                (time(19, 0), None, "calm"),
            ],
        ),
    ]
    rules: list[LoadRule] = []
    rule_id = 1
    for day_group, rows in bands:
        for start, end, level in rows:
            rules.append(_rule(day_group, start, end, level, rule_id))
            rule_id += 1
    return tuple(rules)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MINSK)


def test_default_rules_render_saturday_evening_and_sunday_day_evening() -> None:
    rules = _default_rules()
    saturday = levels_for_day(rules, _SAT)
    sunday = levels_for_day(rules, _SUN)
    assert saturday == (LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_BUSY)
    assert sunday == (LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_CALM)
    text_body = render_forecast(saturday, sunday)
    assert text_body == (
        "🧊 <b>Лёд на выходные</b>\n"
        "\n"
        "<b>Суббота</b>\n"
        "🔴 вечер — весь город на катке\n"
        "\n"
        "<b>Воскресенье</b>\n"
        "🔴 день — самый разгар\n"
        "🟢 вечер — лёд почти ваш\n"
        "\n"
        "На красные часы билет лучше взять заранее 👇"
    )


def test_no_red_means_nothing_to_send() -> None:
    calm = (LEVEL_CALM, LEVEL_CALM, LEVEL_CALM)
    medium = (LEVEL_MEDIUM, LEVEL_MEDIUM, LEVEL_MEDIUM)
    assert render_forecast(calm, calm) is None
    assert render_forecast(medium, (LEVEL_CALM, LEVEL_MEDIUM, LEVEL_MEDIUM)) is None


def test_phrase_rotation_wraps_in_message_order() -> None:
    # Суббота: 🟢 утро и 🔴 вечер. Воскресенье: 🟢 утро и 🔴 день.
    # Вторые фразы — «тихо и просторно» и «самый разгар», третья 🟢 снова первая.
    saturday = (LEVEL_CALM, LEVEL_MEDIUM, LEVEL_BUSY)
    sunday = (LEVEL_CALM, LEVEL_BUSY, LEVEL_CALM)
    text_body = render_forecast(saturday, sunday)
    assert text_body is not None
    assert "🟢 утро — лёд почти ваш" in text_body
    assert "🔴 вечер — весь город на катке" in text_body
    assert "🟢 утро — тихо и просторно" in text_body
    assert "🔴 день — самый разгар" in text_body
    # Третья зелёная (вечер вс, тоже calm, но вечер люднее не нужен: busiest — день).
    # Вечер вс calm и это самая свободная вместе с утром; раньше — утро, так что вечер не дублируется.
    assert text_body.count("🟢") == 2
    assert text_body.count("🔴") == 2


def test_ru_tickets_and_live_line_thresholds() -> None:
    assert ru_tickets(1) == "билет"
    assert ru_tickets(2) == "билета"
    assert ru_tickets(5) == "билетов"
    assert ru_tickets(21) == "билет"
    assert ru_tickets(11) == "билетов"
    sat_levels = (LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_BUSY)
    sun_levels = (LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_CALM)

    def line(left: int, capacity: int = 180, hour: int = 19) -> str | None:
        return live_line_from_slots(
            [
                SaleSlot(
                    arena_name="Замок",
                    local_date=_SAT,
                    starts_at=time(hour, 0),
                    capacity=capacity,
                    sold=capacity - left,
                    held=0,
                )
            ],
            saturday=_SAT,
            sunday=_SUN,
            saturday_levels=sat_levels,
            sunday_levels=sun_levels,
        )

    assert line(23) == "В Замок на сб 19:00 осталось 23 билета."
    assert line(100) is None
    assert line(0) is None
    assert line(1, capacity=10) == "В Замок на сб 19:00 осталось 1 билет."
    assert line(2, capacity=10) == "В Замок на сб 19:00 осталось 2 билета."
    assert line(5, capacity=20) == "В Замок на сб 19:00 осталось 5 билетов."
    assert line(21, capacity=100) == "В Замок на сб 19:00 осталось 21 билет."
    # День субботы тоже busy, но в прогноз попадает только вечер — дневной сеанс не строка.
    assert line(10, capacity=100, hour=14) is None


def test_markup_rows_short_names_and_opt_out_only_weekly() -> None:
    arenas = [
        TicketArena("zamok", "Ледовый дворец", "https://tickets.example/zamok"),
        TicketArena("chizhovka", "Чижовка-арена", "https://tickets.example/chizhovka"),
        TicketArena("konkobezhnaya-arena", "Овал", "https://tickets.example/oval"),
        TicketArena("unknown-rink", "Дворец спорта", "https://tickets.example/palace"),
    ]
    weekly = build_forecast_markup(arenas, webapp_base_url="https://glide.example", opt_out=True)
    assert weekly is not None
    rows = weekly.inline_keyboard
    assert [button.text for button in rows[0]] == [
        "🎟 Замок",
        "🎟 Чижовка",
        "🎟 Конькобежный",
    ]
    assert [button.text for button in rows[1]] == ["🎟 Дворец спорта"]
    assert rows[2][0].text == ALL_SESSIONS_LABEL
    assert rows[2][0].web_app is not None
    assert rows[2][0].web_app.url == "https://glide.example/webapp/ice"
    assert rows[3][0].text == OPT_OUT_LABEL
    assert rows[3][0].callback_data == OPT_OUT_CALLBACK
    assert button_label("katok-na-nemige-u-dvortsa-sporta", "Длинное") == "🎟 Немига"
    assert button_label("ledby", "Ледовый дворец спорта Минской области") == "🎟 ЛДС"

    season = build_forecast_markup(arenas, webapp_base_url="https://glide.example", opt_out=False)
    assert season is not None
    assert all(OPT_OUT_CALLBACK not in [b.callback_data for b in row] for row in season.inline_keyboard)
    stripped = markup_without_optout(weekly)
    assert stripped is not None
    assert all(
        button.callback_data != OPT_OUT_CALLBACK
        for row in stripped.inline_keyboard
        for button in row
    )
    assert len(stripped.inline_keyboard) == 3


def test_season_copy_is_one_line_per_paragraph() -> None:
    assert "в трёх местах" not in SEASON_START_TEXT
    assert "Сезон льда начинается!" in SEASON_START_TEXT
    assert "когда лёд почти ваш, а когда на катке весь город." in SEASON_START_TEXT


def test_forecast_window_gates() -> None:
    thursday = date(2026, 12, 3)
    assert thursday.weekday() == 3
    assert ice_forecast_due(_at(thursday, 18, 0), enabled=True)
    assert ice_forecast_due(_at(thursday, 19, 59), enabled=True)
    assert not ice_forecast_due(_at(thursday, 18, 0), enabled=False)
    assert not ice_forecast_due(_at(thursday, 17, 59), enabled=True)
    assert not ice_forecast_due(_at(thursday, 20, 0), enabled=True)
    assert not ice_forecast_due(_at(thursday - timedelta(days=1), 18, 30), enabled=True)
    first_thursday = date(2026, 10, 29)
    assert first_thursday.weekday() == 3
    assert ice_forecast_due(_at(first_thursday, 18, 30), enabled=True)
    october_thursday = date(2026, 10, 22)
    assert october_thursday.weekday() == 3
    assert not ice_forecast_due(_at(october_thursday, 18, 30), enabled=True)

    feb = date(2027, 2, 1)
    while feb.weekday() != 3:
        feb += timedelta(days=1)
    assert feb <= date(2027, 2, 15)
    assert ice_forecast_due(_at(feb, 18, 30), enabled=True)
    after = date(2027, 2, 16)
    while after.weekday() != 3:
        after += timedelta(days=1)
    assert not ice_forecast_due(_at(after, 18, 30), enabled=True)
    assert campaign_key_for("weekly", thursday) == "ice_forecast_2026-W49"
    assert campaign_key_for("season_start", thursday) == "season_start_2026"
    assert weekend_for(thursday) == (_SAT, _SUN)


class _Bot:
    def __init__(self, blocked: set[int] | None = None) -> None:
        self.blocked = blocked or set()
        self.sent: list[int] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None, **kwargs) -> None:
        if chat_id in self.blocked:
            raise TelegramForbiddenError(
                method=SendMessage(chat_id=chat_id, text=text),
                message="Forbidden: bot was blocked by the user",
            )
        self.sent.append(chat_id)


async def _city(session: AsyncSession, name: str) -> int:
    found = (
        await session.execute(
            text(
                """
                SELECT id FROM cities
                WHERE country = 'BY' AND name = :name
                ORDER BY id LIMIT 1
                """
            ),
            {"name": name},
        )
    ).scalar_one_or_none()
    if found is not None and name == "Минск":
        return int(found)
    created = (
        await session.execute(
            text(
                """
                INSERT INTO cities (name, country, price_group, is_active)
                VALUES (:name, 'BY', 'BY_BASE', true)
                RETURNING id
                """
            ),
            {"name": name},
        )
    ).scalar_one()
    return int(created)


async def _client(session: AsyncSession, *, sandbox: bool = False) -> tuple[int, int]:
    telegram_id = unique_test_telegram_id()
    phone, normalized = belarus_test_phone(telegram_id)
    client_id = (
        await session.execute(
            text(
                """
                INSERT INTO clients (telegram_id, first_name, phone, phone_normalized, is_sandbox)
                VALUES (:tg, 'Тест', :phone, :norm, :sandbox)
                RETURNING id
                """
            ),
            {"tg": telegram_id, "phone": phone, "norm": normalized, "sandbox": sandbox},
        )
    ).scalar_one()
    return int(client_id), telegram_id


async def _session_city(session: AsyncSession, telegram_id: int, city_id: int | None) -> None:
    await session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state, city_id)
            VALUES (:tg, 'idle', :city)
            """
        ),
        {"tg": telegram_id, "city": city_id},
    )


async def _booking_at(session: AsyncSession, client_id: int, arena_id: int) -> None:
    service_id = await require_seed_service_id(session)
    trainer_id = (
        await session.execute(
            text(
                """
                INSERT INTO trainers (status, telegram_id)
                VALUES ('pending_profile', :tg)
                RETURNING id
                """
            ),
            {"tg": unique_test_telegram_id()},
        )
    ).scalar_one()
    slot_id = (
        await session.execute(
            text(
                """
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked')
                RETURNING id
                """
            ),
            {"tid": trainer_id, "d": date(2026, 12, 5)},
        )
    ).scalar_one()
    await session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, arena_id, status)
            VALUES (:tid, :cid, :sid, :svc, :arena, 'confirmed')
            """
        ),
        {
            "tid": trainer_id,
            "cid": client_id,
            "sid": slot_id,
            "svc": service_id,
            "arena": arena_id,
        },
    )


async def _arena(session: AsyncSession, city_id: int, name: str, slug: str, tickets: str | None) -> int:
    arena_id = (
        await session.execute(
            text(
                """
                INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                VALUES (:cid, :name, 'addr', true, true)
                RETURNING id
                """
            ),
            {"cid": city_id, "name": name},
        )
    ).scalar_one()
    await session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, status, tickets_url)
            VALUES (:aid, :cid, :slug, 'published', :url)
            """
        ),
        {"aid": arena_id, "cid": city_id, "slug": slug, "url": tickets},
    )
    return int(arena_id)


async def _skate(
    session: AsyncSession,
    arena_id: int,
    day: date,
    starts: time,
    *,
    kind: str = "public_skate",
) -> None:
    start_at = datetime(day.year, day.month, day.day, starts.hour, starts.minute, tzinfo=MINSK)
    end_at = start_at + timedelta(hours=1)
    await session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                starts_at_local, ends_at_local, currency_code, status, source_id
            )
            VALUES (
                :aid, :kind, :s, :e, :d, :st, :et, 'BYN', 'active', :sid
            )
            """
        ),
        {
            "aid": arena_id,
            "kind": kind,
            "s": start_at,
            "e": end_at,
            "d": day,
            "st": starts,
            "et": time(starts.hour + 1, starts.minute),
            "sid": f"forecast-{arena_id}-{day.isoformat()}-{starts.hour}-{kind}",
        },
    )


@pytest.mark.asyncio
async def test_audience_minsk_booking_and_optout(db_session: AsyncSession) -> None:
    minsk = await _city(db_session, "Минск")
    other = await _city(db_session, "Тестгород-прогноз")
    minsk_arena = await _arena(db_session, minsk, "Арена Минска", "forecast-minsk", "https://t.example/m")
    other_arena = await _arena(db_session, other, "Арена другая", "forecast-other", None)

    _cid, minsk_tg = await _client(db_session)
    await _session_city(db_session, minsk_tg, minsk)

    empty_id, empty_tg = await _client(db_session)
    await _session_city(db_session, empty_tg, None)
    await _booking_at(db_session, empty_id, minsk_arena)

    _other_id, other_tg = await _client(db_session)
    await _session_city(db_session, other_tg, other)
    await _booking_at(db_session, _other_id, minsk_arena)

    _nowhere_id, nowhere_tg = await _client(db_session)

    _sand_id, sand_tg = await _client(db_session, sandbox=True)
    await _session_city(db_session, sand_tg, minsk)

    primary_id, _primary_tg = await _client(db_session)
    family_tg = unique_test_telegram_id()
    await db_session.execute(
        text(
            """
            INSERT INTO client_family_access_members (primary_client_id, member_telegram_id)
            VALUES (:cid, :tg)
            """
        ),
        {"cid": primary_id, "tg": family_tg},
    )
    await _session_city(db_session, family_tg, minsk)

    opted_id, opted_tg = await _client(db_session)
    await _session_city(db_session, opted_tg, minsk)
    await record_ice_forecast_optout(db_session, opted_tg)
    assert opted_id

    empty_other_id, empty_other_tg = await _client(db_session)
    await _session_city(db_session, empty_other_tg, None)
    await _booking_at(db_session, empty_other_id, other_arena)

    # Открывал бот и выбрал Минск, но к тренеру не записывался — тоже аудитория каталога.
    visitor_tg = unique_test_telegram_id()
    await _session_city(db_session, visitor_tg, minsk)

    weekly = set(await fetch_forecast_audience(db_session, respect_optout=True))
    season = set(await fetch_forecast_audience(db_session, respect_optout=False))

    assert minsk_tg in weekly
    assert visitor_tg in weekly
    assert empty_tg in weekly
    assert family_tg in weekly
    assert other_tg not in weekly
    assert nowhere_tg not in weekly
    assert sand_tg not in weekly
    assert empty_other_tg not in weekly
    assert opted_tg not in weekly
    assert opted_tg in season
    assert minsk_tg in season


@pytest.mark.asyncio
async def test_ticket_buttons_only_minsk_cashiers_in_window(db_session: AsyncSession) -> None:
    minsk = await _city(db_session, "Минск")
    other = await _city(db_session, "Тестгород-кассы")
    day = date(2099, 7, 4)
    while day.weekday() != 5:
        day += timedelta(days=1)
    sunday = day + timedelta(days=1)
    outside = day + timedelta(days=10)

    zamok = await _arena(db_session, minsk, "Я Замок", "zamok-btn", "https://tickets.example/zamok")
    # slug в словаре коротких имён — отдельная арена, чтобы не столкнуться с живым zamok.
    named = await _arena(db_session, minsk, "Я Дворец", "forecast-palace", "https://tickets.example/palace")
    no_url = await _arena(db_session, minsk, "Я Без кассы", "forecast-nourl", None)
    quiet = await _arena(db_session, minsk, "Я Вне окна", "forecast-later", "https://tickets.example/later")
    practice = await _arena(db_session, minsk, "Я Тренировка", "forecast-practice", "https://tickets.example/pr")
    away = await _arena(db_session, other, "Я Чужой город", "forecast-away", "https://tickets.example/away")

    await _skate(db_session, zamok, day, time(19, 0))
    await _skate(db_session, named, day, time(12, 0))
    await _skate(db_session, no_url, day, time(19, 0))
    await _skate(db_session, quiet, outside, time(19, 0))
    await _skate(db_session, practice, day, time(19, 0), kind="hockey_practice")
    await _skate(db_session, away, day, time(19, 0))

    found = await list_ticket_arenas(db_session, start=day, end=sunday)
    slugs = {arena.slug for arena in found}
    assert "zamok-btn" in slugs
    assert "forecast-palace" in slugs
    assert "forecast-nourl" not in slugs
    assert "forecast-later" not in slugs
    assert "forecast-practice" not in slugs
    assert "forecast-away" not in slugs
    palace = next(arena for arena in found if arena.slug == "forecast-palace")
    assert button_label(palace.slug, palace.name) == "🎟 Я Дворец"


@pytest.mark.asyncio
async def test_live_line_uses_latest_snapshot(db_session: AsyncSession) -> None:
    minsk = await _city(db_session, "Минск")
    arena_id = await _arena(db_session, minsk, "Замок", "forecast-live", "https://tickets.example/live")
    day = date(2099, 8, 1)
    while day.weekday() != 5:
        day += timedelta(days=1)
    sunday = day + timedelta(days=1)
    await _skate(db_session, arena_id, day, time(19, 0))
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sales_snapshots (
                arena_id, local_date, starts_at_local, observed_at, capacity, sold, held, source
            )
            VALUES
                (:aid, :d, TIME '19:00', '2099-08-01T10:00:00+03:00', 180, 0, 0, 'korona'),
                (:aid, :d, TIME '19:00', '2099-08-01T16:00:00+03:00', 180, 157, 0, 'korona')
            """
        ),
        {"aid": arena_id, "d": day},
    )
    slots = await load_sale_slots(db_session, saturday=day, sunday=sunday)
    assert len(slots) == 1
    assert slots[0].sold == 157
    line = live_line_from_slots(
        slots,
        saturday=day,
        sunday=sunday,
        saturday_levels=(LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_BUSY),
        sunday_levels=(LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_CALM),
    )
    assert line == "В Замок на сб 19:00 осталось 23 билета."


@pytest.mark.asyncio
async def test_repeat_send_skips_and_forbidden_is_failed(db_session: AsyncSession) -> None:
    minsk = await _city(db_session, "Минск")
    _ok_id, ok_tg = await _client(db_session)
    await _session_city(db_session, ok_tg, minsk)
    _also_id, also_tg = await _client(db_session)
    await _session_city(db_session, also_tg, minsk)
    _blocked_id, blocked_tg = await _client(db_session)
    await _session_city(db_session, blocked_tg, minsk)

    settings = Settings()
    bot = _Bot(blocked={blocked_tg})
    on = date(2099, 6, 1)
    await send_ice_forecast(
        db_session,
        bot,  # type: ignore[arg-type]
        "season_start",
        settings=settings,
        on=on,
        send_delay_sec=0,
    )
    assert ok_tg in bot.sent
    assert also_tg in bot.sent
    assert blocked_tg not in bot.sent

    rows = (
        await db_session.execute(
            text(
                """
                SELECT telegram_id, status FROM client_broadcast_log
                WHERE campaign_key = 'season_start_2026'
                  AND telegram_id = ANY(:ids)
                """
            ),
            {"ids": [ok_tg, also_tg, blocked_tg]},
        )
    ).all()
    status = {int(row[0]): row[1] for row in rows}
    assert status[ok_tg] == "sent"
    assert status[also_tg] == "sent"
    assert status[blocked_tg] == "failed"

    bot.sent.clear()
    await send_ice_forecast(
        db_session,
        bot,  # type: ignore[arg-type]
        "season_start",
        settings=settings,
        on=on,
        send_delay_sec=0,
    )
    assert ok_tg not in bot.sent
    assert also_tg not in bot.sent
    assert blocked_tg not in bot.sent


@pytest.mark.asyncio
async def test_db_rules_match_seeded_weekend(db_session: AsyncSession) -> None:
    invalidate_session_load_cache()
    ctx = await load_session_load_context(db_session)
    saturday = levels_for_day(ctx.rules, _SAT)
    sunday = levels_for_day(ctx.rules, _SUN)
    assert saturday == (LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_BUSY)
    assert sunday == (LEVEL_MEDIUM, LEVEL_BUSY, LEVEL_CALM)
    body = render_forecast(saturday, sunday)
    assert body is not None
    assert "🔴 вечер — весь город на катке" in body
    assert "🔴 день — самый разгар" in body
    assert "🟢 вечер — лёд почти ваш" in body


def test_optout_markup_drops_only_the_forecast_button() -> None:
    markup = build_forecast_markup(
        [TicketArena("zamok", "Замок", "https://tickets.example/z")],
        webapp_base_url="https://glide.example",
        opt_out=True,
    )
    assert isinstance(markup, InlineKeyboardMarkup)
    kept = markup_without_optout(markup)
    assert kept is not None
    texts = [button.text for row in kept.inline_keyboard for button in row]
    assert OPT_OUT_LABEL not in texts
    assert "🎟 Замок" in texts
    assert ALL_SESSIONS_LABEL in texts
