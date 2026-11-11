"""Рассылка «Кто кого» белорусским клиентам: сегмент by_clients, журнал в БД, волны, отписка."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_forecast import record_ice_forecast_optout
from src.application.release_comms_use_cases import (
    KK_PROMO_OPTOUT_CALLBACK,
    broadcast_release_comms,
    build_webapp_markup,
    fetch_audience_telegram_ids,
    markup_without_kk_optout,
    parse_release_comms_file,
    record_kk_promo_optout,
    wave_targets,
)
from src.shared.config import Settings
from tests.application.test_ice_forecast import _arena, _booking_at, _Bot, _city, _client, _session_city
from tests.conftest import unique_test_telegram_id

CLIENTS_MD = """---
release_id: {rid}
audience: clients
segment: by_clients
button_text: Играть
webapp_path: /webapp/kto-kogo?src=push1
---

<b>Привет</b>
"""


def _spec(tmp_path: Path, rid: str = "kk-test-wave"):
    path = tmp_path / "m.clients.md"
    path.write_text(CLIENTS_MD.format(rid=rid), encoding="utf-8")
    return parse_release_comms_file(path)


async def _ru_city(session: AsyncSession) -> int:
    return int(
        (
            await session.execute(
                text(
                    "INSERT INTO cities (name, country, price_group, is_active)"
                    " VALUES ('Тест-РФ', 'RU', 'RU_BASE', true) RETURNING id"
                )
            )
        ).scalar_one()
    )


def test_parse_by_clients_segment(tmp_path: Path) -> None:
    assert _spec(tmp_path).segment == "by_clients"
    bad = tmp_path / "t.md"
    bad.write_text("---\naudience: trainers\nsegment: by_clients\n---\nx", encoding="utf-8")
    with pytest.raises(ValueError, match="segment"):
        parse_release_comms_file(bad)


def test_markup_has_webapp_button_and_optout_row(tmp_path: Path) -> None:
    settings = Settings(webapp_base_url="https://glide.test")
    markup = build_webapp_markup(settings, _spec(tmp_path))
    assert markup is not None
    first, second = markup.inline_keyboard
    assert first[0].web_app.url == "https://glide.test/webapp/kto-kogo?src=push1"
    assert second[0].callback_data == KK_PROMO_OPTOUT_CALLBACK
    stripped = markup_without_kk_optout(markup)
    assert stripped is not None and len(stripped.inline_keyboard) == 1
    only = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="x", callback_data=KK_PROMO_OPTOUT_CALLBACK)]]
    )
    assert markup_without_kk_optout(only) is None


@pytest.mark.asyncio
async def test_by_clients_audience_is_belarus_only_without_sandbox_and_optouts(db_session: AsyncSession) -> None:
    by = await _city(db_session, "Минск")
    ru = await _ru_city(db_session)
    by_arena = await _arena(db_session, by, "Арена BY", "kk-by", None)
    ru_arena = await _arena(db_session, ru, "Арена RU", "kk-ru", None)

    _id, by_tg = await _client(db_session)
    await _session_city(db_session, by_tg, by)
    _id, ru_tg = await _client(db_session)
    await _session_city(db_session, ru_tg, ru)
    sand_id, sand_tg = await _client(db_session, sandbox=True)
    await _session_city(db_session, sand_tg, by)
    # Без города в сессии — по записи на арене страны.
    by_book_id, by_book_tg = await _client(db_session)
    await _session_city(db_session, by_book_tg, None)
    await _booking_at(db_session, by_book_id, by_arena)
    ru_book_id, ru_book_tg = await _client(db_session)
    await _session_city(db_session, ru_book_tg, None)
    await _booking_at(db_session, ru_book_id, ru_arena)
    # Ни города, ни записи — страну не знаем, не рассылаем.
    _id, unknown_tg = await _client(db_session)
    visitor_tg = unique_test_telegram_id()
    await _session_city(db_session, visitor_tg, by)
    out_id, out_tg = await _client(db_session)
    await _session_city(db_session, out_tg, by)
    await record_kk_promo_optout(db_session, out_tg)
    # Отписка от прогноза льда не отписывает от игры (и наоборот).
    _id, ice_out_tg = await _client(db_session)
    await _session_city(db_session, ice_out_tg, by)
    await record_ice_forecast_optout(db_session, ice_out_tg)
    await record_ice_forecast_optout(db_session, out_tg)
    assert sand_id and out_id

    got = set(await fetch_audience_telegram_ids(db_session, "clients", segment="by_clients"))
    assert {by_tg, by_book_tg, visitor_tg, ice_out_tg} <= got
    assert not ({ru_tg, sand_tg, ru_book_tg, unknown_tg, out_tg} & got)


@pytest.mark.asyncio
async def test_waves_journal_and_repeat_does_not_duplicate(db_session: AsyncSession, tmp_path: Path) -> None:
    by = await _city(db_session, "Минск")
    tgs = []
    for _ in range(10):
        _id, tg = await _client(db_session)
        await _session_city(db_session, tg, by)
        tgs.append(tg)
    spec = _spec(tmp_path, "kk-wave-test")
    settings = Settings(webapp_base_url="https://glide.test")
    audience = set(await fetch_audience_telegram_ids(db_session, "clients", segment="by_clients"))
    assert set(tgs) <= audience

    dry = await broadcast_release_comms(db_session, spec, settings=settings, dry_run=True, percent=10)
    assert dry.total == len(audience)
    assert dry.would_send == max(1, -(-len(audience) // 10))
    assert dry.sample_ids and dry.sent == 0
    count = (
        await db_session.execute(text("SELECT count(*) FROM client_broadcast_log WHERE campaign_key = 'kk-wave-test'"))
    ).scalar_one()
    assert count == 0

    bot = _Bot()
    first = await broadcast_release_comms(
        db_session, spec, settings=settings, bot=bot, percent=50, limit=3, send_delay_sec=0
    )
    assert first.sent == 3 and len(bot.sent) == 3
    # Второй запуск с теми же параметрами досылает остаток волны (50% из 10 — пятеро), а не тех же.
    second = await broadcast_release_comms(
        db_session, spec, settings=settings, bot=bot, percent=50, limit=3, send_delay_sec=0
    )
    assert second.sent == 2 and len(set(bot.sent)) == len(bot.sent) == 5
    full = await broadcast_release_comms(db_session, spec, settings=settings, bot=bot, send_delay_sec=0)
    assert len(set(bot.sent)) == len(bot.sent) == len(audience)
    assert full.skipped == 5
    again = await broadcast_release_comms(db_session, spec, settings=settings, bot=bot, send_delay_sec=0)
    assert again.sent == 0 and len(bot.sent) == len(audience)
    logged = (
        await db_session.execute(
            text("SELECT count(*) FROM client_broadcast_log WHERE campaign_key = 'kk-wave-test' AND status = 'sent'")
        )
    ).scalar_one()
    assert logged == len(audience)


@pytest.mark.asyncio
async def test_blocked_user_is_logged_failed_and_not_retried(db_session: AsyncSession, tmp_path: Path) -> None:
    by = await _city(db_session, "Минск")
    _id, ok_tg = await _client(db_session)
    await _session_city(db_session, ok_tg, by)
    _id, blocked_tg = await _client(db_session)
    await _session_city(db_session, blocked_tg, by)
    spec = _spec(tmp_path, "kk-blocked-test")
    bot = _Bot(blocked={blocked_tg})
    res = await broadcast_release_comms(db_session, spec, settings=Settings(), bot=bot, send_delay_sec=0)
    assert ok_tg in bot.sent and blocked_tg not in bot.sent and res.failed >= 1
    bot.sent.clear()
    await broadcast_release_comms(db_session, spec, settings=Settings(), bot=bot, send_delay_sec=0)
    assert bot.sent == []


@pytest.mark.asyncio
async def test_percent_only_for_by_clients(db_session: AsyncSession, tmp_path: Path) -> None:
    path = tmp_path / "a.clients.md"
    path.write_text("---\nrelease_id: x\naudience: clients\n---\nhi", encoding="utf-8")
    with pytest.raises(ValueError, match="percent"):
        await broadcast_release_comms(
            db_session, parse_release_comms_file(path), settings=Settings(), dry_run=True, percent=10
        )


@pytest.mark.asyncio
async def test_optout_is_idempotent_and_independent_per_kind(db_session: AsyncSession) -> None:
    tg = unique_test_telegram_id()
    await record_kk_promo_optout(db_session, tg)
    await record_kk_promo_optout(db_session, tg)
    await record_ice_forecast_optout(db_session, tg)
    kinds = (
        (
            await db_session.execute(
                text("SELECT kind FROM client_broadcast_optouts WHERE telegram_id = :t ORDER BY kind"), {"t": tg}
            )
        )
        .scalars()
        .all()
    )
    assert kinds == ["ice_forecast", "kk_promo"]


@pytest.mark.asyncio
async def test_optout_callback_records_and_removes_the_button(db_session: AsyncSession) -> None:
    from types import SimpleNamespace

    from src.bot.handlers.client_handlers import kk_promo_optout_callback

    tg = unique_test_telegram_id()
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Играть", url="https://t.me/x")],
            [InlineKeyboardButton(text="Не присылать такое", callback_data=KK_PROMO_OPTOUT_CALLBACK)],
        ]
    )
    edited: list = []
    answers: list = []

    async def edit_reply_markup(reply_markup=None):
        edited.append(reply_markup)

    async def answer(text=None, **kwargs):
        answers.append(text)

    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=tg),
        message=SimpleNamespace(reply_markup=markup, edit_reply_markup=edit_reply_markup),
        answer=answer,
    )
    await kk_promo_optout_callback(callback)  # type: ignore[arg-type]
    kinds = (
        (await db_session.execute(text("SELECT kind FROM client_broadcast_optouts WHERE telegram_id = :t"), {"t": tg}))
        .scalars()
        .all()
    )
    assert kinds == ["kk_promo"]
    assert len(edited[0].inline_keyboard) == 1 and answers == ["Больше не пришлём"]


@pytest.mark.asyncio
async def test_draft_is_never_sent_for_real_but_can_be_previewed(db_session: AsyncSession, tmp_path: Path) -> None:
    path = tmp_path / "d.clients.md"
    path.write_text(
        CLIENTS_MD.format(rid="kk-draft").replace("segment: by_clients", "draft: true\nsegment: by_clients"),
        encoding="utf-8",
    )
    spec = parse_release_comms_file(path)
    assert spec.draft is True
    with pytest.raises(ValueError, match="draft"):
        await broadcast_release_comms(db_session, spec, settings=Settings(), bot=_Bot(), send_delay_sec=0)
    assert (await broadcast_release_comms(db_session, spec, settings=Settings(), dry_run=True)).dry_run
    preview_bot = _Bot()
    await broadcast_release_comms(db_session, spec, settings=Settings(), bot=preview_bot, chat_id=7, send_delay_sec=0)
    assert preview_bot.sent == [7]


def test_repo_draft_file_parses_and_is_a_draft() -> None:
    path = Path(__file__).resolve().parents[2] / "docs/release-comms/2026-11-XX-kto-kogo.clients.md"
    spec = parse_release_comms_file(path)
    assert (spec.draft, spec.segment, spec.audience) == (True, "by_clients", "clients")
    assert spec.webapp_path == "/webapp/kto-kogo?src=push1"
    assert "×" not in spec.html_body and "%" not in spec.html_body


# --- Фильтры шапки: cities и exclude_campaigns -------------------------------------------------


def _filtered_spec(tmp_path: Path, rid: str, extra: str):
    path = tmp_path / f"{rid}.clients.md"
    path.write_text(
        CLIENTS_MD.format(rid=rid).replace("segment: by_clients", f"segment: by_clients\n{extra}"), encoding="utf-8"
    )
    return parse_release_comms_file(path)


def test_parse_cities_and_exclude_campaigns(tmp_path: Path) -> None:
    spec = _filtered_spec(
        tmp_path, "kk-parse", "cities: Орша,  Могилёв , Барановичи, Орша\nexclude_campaigns: a-1, b-2"
    )
    assert spec.cities == ("Орша", "Могилёв", "Барановичи")
    assert spec.exclude_campaigns == ("a-1", "b-2")
    assert (_spec(tmp_path).cities, _spec(tmp_path).exclude_campaigns) == (None, None)
    with pytest.raises(ValueError, match="cities"):
        _filtered_spec(tmp_path, "kk-empty", "cities: , ")
    other = tmp_path / "o.clients.md"
    other.write_text("---\naudience: clients\ncities: Орша\n---\nhi", encoding="utf-8")
    with pytest.raises(ValueError, match="by_clients"):
        parse_release_comms_file(other)


@pytest.mark.asyncio
async def test_cities_filter_ignores_case_and_yo_and_uses_booking_city(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    sfx = unique_test_telegram_id()
    yo = await _city(db_session, f"Тёстоград{sfx}")
    plain = await _city(db_session, f"Другойград{sfx}")
    skip = await _city(db_session, f"Мимоград{sfx}")
    yo_arena = await _arena(db_session, yo, "Арена ё", f"kk-yo-{sfx}", None)
    skip_arena = await _arena(db_session, skip, "Арена мимо", f"kk-skip-{sfx}", None)

    _id, yo_tg = await _client(db_session)
    await _session_city(db_session, yo_tg, yo)
    _id, plain_tg = await _client(db_session)
    await _session_city(db_session, plain_tg, plain)
    _id, skip_tg = await _client(db_session)
    await _session_city(db_session, skip_tg, skip)
    # Нет города в сессии — берётся город арены записи.
    book_id, book_tg = await _client(db_session)
    await _session_city(db_session, book_tg, None)
    await _booking_at(db_session, book_id, yo_arena)
    # Город сессии важнее записи: записан в выбранном городе, но живёт в другом — не попадает.
    moved_id, moved_tg = await _client(db_session)
    await _session_city(db_session, moved_tg, skip)
    await _booking_at(db_session, moved_id, yo_arena)
    other_id, other_tg = await _client(db_session)
    await _session_city(db_session, other_tg, None)
    await _booking_at(db_session, other_id, skip_arena)

    spec = _filtered_spec(tmp_path, "kk-cities", f"cities: ТЕСТОГРАД{sfx}, другойград{sfx}")
    res = await broadcast_release_comms(db_session, spec, settings=Settings(), dry_run=True)
    assert res.filters is not None
    assert res.filters["cities"] == {f"ТЕСТОГРАД{sfx}": 2, f"другойград{sfx}": 1}
    assert res.total == res.filters["after_filters"] == 3
    bot = _Bot()
    await broadcast_release_comms(db_session, spec, settings=Settings(), bot=bot, send_delay_sec=0)
    assert set(bot.sent) == {yo_tg, plain_tg, book_tg}
    assert not ({skip_tg, moved_tg, other_tg} & set(bot.sent))


@pytest.mark.asyncio
async def test_unknown_city_is_an_error_before_sending(db_session: AsyncSession, tmp_path: Path) -> None:
    await _city(db_session, "Минск")
    spec = _filtered_spec(tmp_path, "kk-unknown", "cities: Минск, Нетакогограда")
    bot = _Bot()
    with pytest.raises(ValueError, match="Нетакогограда"):
        await broadcast_release_comms(db_session, spec, settings=Settings(), dry_run=True)
    with pytest.raises(ValueError, match="Нетакогограда"):
        await broadcast_release_comms(db_session, spec, settings=Settings(), bot=bot, send_delay_sec=0)
    assert bot.sent == []
    # Российский город для сегмента by_clients тоже неизвестен.
    ru = await _ru_city(db_session)
    assert ru
    with pytest.raises(ValueError, match="Тест-РФ"):
        await broadcast_release_comms(
            db_session, _filtered_spec(tmp_path, "kk-ru", "cities: Тест-РФ"), settings=Settings(), dry_run=True
        )


@pytest.mark.asyncio
async def test_exclude_campaigns_skips_recipients_of_any_status(db_session: AsyncSession, tmp_path: Path) -> None:
    sfx = unique_test_telegram_id()
    city = await _city(db_session, f"Исклград{sfx}")
    tgs = []
    for _ in range(4):
        _id, tg = await _client(db_session)
        await _session_city(db_session, tg, city)
        tgs.append(tg)
    sent_tg, failed_tg, elsewhere_tg, fresh_tg = tgs
    for tg, key, status in (
        (sent_tg, f"kk-prev-{sfx}", "sent"),
        (failed_tg, f"kk-prev2-{sfx}", "failed"),
        (elsewhere_tg, f"kk-unrelated-{sfx}", "sent"),
    ):
        await db_session.execute(
            text("INSERT INTO client_broadcast_log (telegram_id, campaign_key, status) VALUES (:t, :k, :s)"),
            {"t": tg, "k": key, "s": status},
        )
    spec = _filtered_spec(
        tmp_path, "kk-excl", f"cities: Исклград{sfx}\nexclude_campaigns: kk-prev-{sfx}, kk-prev2-{sfx}"
    )
    dry = await broadcast_release_comms(db_session, spec, settings=Settings(), dry_run=True)
    assert dry.filters == {
        "by_clients_total": dry.filters["by_clients_total"],
        "cities": {f"Исклград{sfx}": 4},
        "excluded_by_campaigns": 2,
        "after_filters": 2,
    }
    bot = _Bot()
    await broadcast_release_comms(db_session, spec, settings=Settings(), bot=bot, send_delay_sec=0)
    assert sorted(bot.sent) == sorted([elsewhere_tg, fresh_tg])
    # Без cities: исключение кампаний работает по всей BY-аудитории.
    only_excl = _filtered_spec(tmp_path, "kk-excl-only", f"exclude_campaigns: kk-prev-{sfx}")
    got = await broadcast_release_comms(db_session, only_excl, settings=Settings(), dry_run=True)
    assert got.filters is not None and "cities" not in got.filters
    assert got.filters["excluded_by_campaigns"] == 1


@pytest.mark.asyncio
async def test_without_filter_fields_audience_and_result_are_unchanged(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    by = await _city(db_session, "Минск")
    for _ in range(3):
        _id, tg = await _client(db_session)
        await _session_city(db_session, tg, by)
    spec = _spec(tmp_path, "kk-nofilter")
    base = await fetch_audience_telegram_ids(db_session, "clients", segment="by_clients")
    dry = await broadcast_release_comms(db_session, spec, settings=Settings(), dry_run=True, percent=50, limit=2)
    assert dry.filters is None
    assert dry.total == len(base)
    assert dry.sample_ids == wave_targets("kk-nofilter", base, set(), percent=50, limit=2)[:5]
