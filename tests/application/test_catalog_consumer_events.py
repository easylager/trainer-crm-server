"""catalog_consumer_events — WAU, C-B, дедуп, приватность, ретеншн (TASK-189)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.application import catalog_consumer_events as cce
from src.application.catalog_consumer_events import (
    KIND_MINIAPP_CATALOG_ENTRY,
    KIND_PUBLIC_CONTACT_CLICK,
    KIND_PUBLIC_PAGE_VIEW,
    KIND_PUBLIC_TELEGRAM_CTA,
    event_dedup_hash,
    get_catalog_demand_pulse,
    get_catalog_top_arenas_by_events,
    get_catalog_virality_cb_metrics,
    get_catalog_wau,
    get_catalog_weekly_unique_by_city,
    is_share_attributed_deeplink_open,
    metrics_comparable_since,
    public_actor_hash,
    purge_old_catalog_consumer_events,
    record_catalog_consumer_event,
    resolve_entry_scope,
    telegram_actor_hash,
    telegram_launch_context,
)
from src.ingestion.loop import run_ttl_tick
from src.shared.config import Settings

_TEST_SECRET = "test-catalog-actor-secret-0123456789abcdef"


@pytest.fixture(autouse=True)
def _actor_secret(monkeypatch):
    """Явный тестовый секрет; сопоставимый ряд — из базы, не из окружения разработчика."""
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _TEST_SECRET)
    monkeypatch.delenv("CATALOG_METRICS_COMPARABLE_SINCE", raising=False)


async def _insert_event(db_session, *, kind: str, actor: str | None, at: datetime, city_id=None, arena_id=None,
                        surface: str = "place_page", payload: str = "{}", dedup: bool = True) -> None:
    dk = (
        event_dedup_hash(kind=kind, surface=surface, actor_hash=actor, day=cce.catalog_event_day_minsk(at),
                         city_id=city_id, arena_id=arena_id)
        if dedup
        else None
    )
    await db_session.execute(
        text(
            """
            INSERT INTO catalog_consumer_events
                (kind, surface, actor_hash, occurred_at, city_id, arena_id, dedup_key, payload)
            VALUES (:kind, :surface, :actor, :at, :city, :arena, :dk, CAST(:payload AS jsonb))
            """
        ),
        {"kind": kind, "surface": surface, "actor": actor, "at": at, "city": city_id, "arena": arena_id,
         "dk": dk, "payload": payload},
    )


async def _city_and_arenas(db_session, n: int) -> tuple[int, list[int]]:
    city_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, price_group, is_active, sort_order)
                    VALUES (:name, 'BY', 'default', true, 0)
                    RETURNING id
                    """
                ),
                {"name": f"Тест-189-{uuid.uuid4().hex[:6]}"},
            )
        ).scalar_one()
    )
    arena_ids: list[int] = []
    for i in range(n):
        arena_ids.append(
            int(
                (
                    await db_session.execute(
                        text(
                            """
                            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                            VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                            RETURNING id
                            """
                        ),
                        {"cid": city_id, "name": f"Арена-189-{i}"},
                    )
                ).scalar_one()
            )
        )
    await db_session.flush()
    return city_id, arena_ids


# --- приватность: fail closed --------------------------------------------------------------


def test_no_secret_means_no_actor_hash(monkeypatch, caplog) -> None:
    """Ревью #2: без CATALOG_ACTOR_HMAC_SECRET псевдонимы не пишутся — ни SECRET_KEY, ни литерал."""
    monkeypatch.delenv("CATALOG_ACTOR_HMAC_SECRET", raising=False)
    monkeypatch.setenv("SECRET_KEY", "x" * 64)
    monkeypatch.setattr(cce, "_missing_secret_logged", False)
    monkeypatch.setattr("src.shared.config.get_settings", lambda: Settings(catalog_actor_hmac_secret=None))
    with caplog.at_level(logging.ERROR, logger=cce.__name__):
        assert telegram_actor_hash(4242) is None
        assert public_actor_hash(client_ip="1.2.3.4", user_agent="UA") is None
        assert telegram_actor_hash(4243) is None
    errors = [r for r in caplog.records if "CATALOG_ACTOR_HMAC_SECRET" in r.getMessage()]
    assert len(errors) == 1, "ошибка в лог — один раз на процесс"


def test_short_secret_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "short")
    monkeypatch.setattr("src.shared.config.get_settings", lambda: Settings(catalog_actor_hmac_secret=None))
    assert telegram_actor_hash(1) is None


def test_hash_depends_on_secret_only_not_day(monkeypatch) -> None:
    a = telegram_actor_hash(4242)
    assert a is not None and a == telegram_actor_hash(4242)
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "another-secret-0123456789abcdef-xyz")
    assert telegram_actor_hash(4242) != a


async def test_without_secret_event_recorded_without_actor(monkeypatch, db_session) -> None:
    monkeypatch.delenv("CATALOG_ACTOR_HMAC_SECRET", raising=False)
    monkeypatch.setattr("src.shared.config.get_settings", lambda: Settings(catalog_actor_hmac_secret=None))
    ok = await record_catalog_consumer_event(
        db_session, kind=KIND_PUBLIC_PAGE_VIEW, surface="place_page",
        actor_hash=public_actor_hash(client_ip="9.9.9.9", user_agent="UA-nosecret"),
    )
    assert ok is True
    row = (
        await db_session.execute(
            text("SELECT actor_hash, dedup_key FROM catalog_consumer_events ORDER BY id DESC LIMIT 1")
        )
    ).one()
    assert row.actor_hash is None and row.dedup_key is None


# --- WAU / дедуп ----------------------------------------------------------------------------


async def test_record_and_wau_dedup(db_session) -> None:
    actor = telegram_actor_hash(4242)
    ok1 = await record_catalog_consumer_event(
        db_session, kind=KIND_MINIAPP_CATALOG_ENTRY, surface="miniapp_ice", actor_hash=actor
    )
    ok2 = await record_catalog_consumer_event(
        db_session, kind=KIND_MINIAPP_CATALOG_ENTRY, surface="miniapp_ice", actor_hash=actor
    )
    assert ok1 is True
    assert ok2 is False
    wau = await get_catalog_wau(db_session, days=7)
    assert wau["unique_actors"] >= 1


async def test_stable_actor_counts_once_per_week(db_session) -> None:
    """AC-1: один актёр 7 дней подряд → 1 недельный уникальный."""
    actor = telegram_actor_hash(9001)
    base = datetime.now(timezone.utc) - timedelta(days=6, hours=1)
    for offset in range(7):
        await _insert_event(db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor=actor, at=base + timedelta(days=offset))
    await db_session.flush()
    wau = await get_catalog_wau(db_session, days=7, as_of=base + timedelta(days=6, hours=2))
    assert wau["unique_actors"] == 1


async def test_dedup_per_arena_same_day(db_session) -> None:
    """AC-2: один актёр, шесть арен за день → шесть строк."""
    city_id, arena_ids = await _city_and_arenas(db_session, 6)
    actor = telegram_actor_hash(555)
    for arena_id in arena_ids:
        ok = await record_catalog_consumer_event(
            db_session, kind=KIND_PUBLIC_PAGE_VIEW, surface="place_page", actor_hash=actor,
            city_id=city_id, arena_id=arena_id,
        )
        assert ok is True
    count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM catalog_consumer_events WHERE actor_hash = :a AND kind = :k"),
            {"a": actor, "k": KIND_PUBLIC_PAGE_VIEW},
        )
    ).scalar_one()
    assert int(count) == 6


async def test_shell_and_arena_card_of_one_deeplink_open_are_one_row(db_session) -> None:
    """C-B: shell и карточка арены одного входа по arena_X больше не дают две строки."""
    city_id, (arena_id,) = await _city_and_arenas(db_session, 1)
    actor = telegram_actor_hash(31337)
    sp = f"arena_{arena_id}"
    for surface, body_arena in (("miniapp_shell", None), ("miniapp_arena", arena_id)):
        cid, aid = await resolve_entry_scope(db_session, start_param=sp, city_id=None, arena_id=body_arena)
        await record_catalog_consumer_event(
            db_session, kind=KIND_MINIAPP_CATALOG_ENTRY, surface=surface, actor_hash=actor,
            city_id=cid, arena_id=aid, start_param=sp,
        )
    rows = (
        await db_session.execute(
            text("SELECT surface, city_id, arena_id FROM catalog_consumer_events WHERE actor_hash = :a"),
            {"a": actor},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].city_id == city_id and rows[0].arena_id == arena_id


async def test_resolve_entry_scope_derives_city(db_session) -> None:
    """Ревью #7: city_id у miniapp_shell / miniapp_arena — из арены или диплинка."""
    city_id, (arena_id,) = await _city_and_arenas(db_session, 1)
    assert await resolve_entry_scope(db_session, start_param=None, city_id=None, arena_id=arena_id) == (
        city_id, arena_id)
    assert await resolve_entry_scope(db_session, start_param=f"arena_{arena_id}_s_5", city_id=None,
                                     arena_id=None) == (city_id, arena_id)
    assert await resolve_entry_scope(db_session, start_param=f"catalog_{city_id}_skate", city_id=None,
                                     arena_id=None) == (city_id, None)
    assert await resolve_entry_scope(db_session, start_param="arena_999999999", city_id=None,
                                     arena_id=None) == (None, None)


async def test_parallel_insert_of_one_event_gives_one_row() -> None:
    """AC-5: по-настоящему параллельно — 8 отдельных сессий/соединений, asyncio.gather.

    Пишет вне транзакции теста (иначе это одно соединение и не гонка) и убирает за собой.
    """
    engine = create_async_engine(Settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    actor = telegram_actor_hash(10_000_000 + uuid.uuid4().int % 1_000_000)

    async def one() -> bool:
        async with factory() as session:
            return await record_catalog_consumer_event(
                session, kind=KIND_MINIAPP_CATALOG_ENTRY, surface="miniapp_ice", actor_hash=actor
            )

    try:
        results = await asyncio.gather(*(one() for _ in range(8)))
        async with factory() as session:
            n = (
                await session.execute(
                    text("SELECT COUNT(*) FROM catalog_consumer_events WHERE actor_hash = :a"), {"a": actor}
                )
            ).scalar_one()
        assert int(n) == 1
        assert results.count(True) == 1
    finally:
        async with factory() as session:
            await session.execute(text("DELETE FROM catalog_consumer_events WHERE actor_hash = :a"), {"a": actor})
            await session.commit()
        await engine.dispose()


# --- C-B --------------------------------------------------------------------------------------


def test_share_attribution_rules() -> None:
    """AC-4 + ревью #7: голый catalog (/go) и вход не из чата (CTA публички) — не share-open."""
    assert is_share_attributed_deeplink_open("catalog", chat_type="private") is False
    assert is_share_attributed_deeplink_open("catalog_1_skate", chat_type=None) is False
    assert is_share_attributed_deeplink_open("arena_5", chat_type="") is False
    assert is_share_attributed_deeplink_open("something_else", chat_type="group") is False
    assert is_share_attributed_deeplink_open("arena_5", chat_type="sender") is True
    assert is_share_attributed_deeplink_open("catalog_1_skate", chat_type="group") is True


def test_telegram_launch_context_reads_chat_type_and_start_param() -> None:
    raw = "query_id=x&user=%7B%22id%22%3A1%7D&chat_type=group&chat_instance=1&start_param=arena_7&hash=abc"
    assert telegram_launch_context(raw) == {"chat_type": "group", "start_param": "arena_7"}
    assert telegram_launch_context(None) == {}


async def test_virality_metrics_empty(db_session) -> None:
    metrics = await get_catalog_virality_cb_metrics(db_session, days=7)
    assert metrics["metric"] == "catalog_virality_cb"
    assert "share_to_deeplink_open_pct" in metrics


async def test_virality_metrics_share_attribution_breakdown(db_session) -> None:
    now = datetime.now(timezone.utc)
    await _insert_event(
        db_session,
        kind=KIND_PUBLIC_PAGE_VIEW,
        actor=telegram_actor_hash(71_001),
        at=now,
        payload='{"src": "tg", "s": "5"}',
        dedup=False,
    )
    await _insert_event(
        db_session,
        kind=KIND_PUBLIC_PAGE_VIEW,
        actor=telegram_actor_hash(71_002),
        at=now,
        payload='{"src": "wa"}',
        dedup=False,
    )
    await _insert_event(
        db_session,
        kind=KIND_PUBLIC_TELEGRAM_CTA,
        actor=None,
        at=now,
        payload='{"ingress": "public_cta", "src": "tg"}',
        dedup=False,
    )
    metrics = await get_catalog_virality_cb_metrics(db_session, days=1, as_of=now + timedelta(minutes=1))
    assert metrics["public_page_view_by_src"]["tg"] >= 1
    assert metrics["public_page_view_by_src"]["wa"] >= 1
    assert metrics["public_page_view_with_session"] >= 1
    assert metrics["public_telegram_cta_clicks_by_src"]["tg"] >= 1


async def test_cb_counts_only_share_attributed_opens(db_session) -> None:
    now = datetime.now(timezone.utc)
    before = (await get_catalog_virality_cb_metrics(db_session, days=1, as_of=now + timedelta(minutes=1)))
    flags = [("arena_1", True), ("catalog", False), ("arena_2", False)]
    for i, (_sp, share) in enumerate(flags):
        await _insert_event(
            db_session, kind=KIND_MINIAPP_CATALOG_ENTRY, actor=telegram_actor_hash(70_000 + i), at=now,
            surface="miniapp_shell", payload=f'{{"share_deeplink": {str(share).lower()}}}',
        )
    await _insert_event(db_session, kind=KIND_PUBLIC_TELEGRAM_CTA, actor=None, at=now, dedup=False)
    after = await get_catalog_virality_cb_metrics(db_session, days=1, as_of=now + timedelta(minutes=1))
    assert after["miniapp_deeplink_entries"] - before["miniapp_deeplink_entries"] == 1
    assert after["public_telegram_cta_clicks"] - before["public_telegram_cta_clicks"] == 1


# --- отчёт: недели × города, топ арен, сопоставимый ряд -------------------------------------


async def test_weekly_by_city_and_top_arenas(db_session) -> None:
    city_id, arena_ids = await _city_and_arenas(db_session, 2)
    now = datetime.now(timezone.utc)
    for i, arena_id in enumerate(arena_ids):
        for k in range(i + 1):
            await _insert_event(
                db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor=telegram_actor_hash(80_000 + k), at=now,
                city_id=city_id, arena_id=arena_id,
            )
    await db_session.flush()
    weekly = await get_catalog_weekly_unique_by_city(db_session, weeks=1, as_of=now + timedelta(minutes=1))
    mine = [r for r in weekly if r["city_id"] == city_id]
    assert mine and mine[0]["unique_actors"] == 2 and mine[0]["events"] == 3
    top = await get_catalog_top_arenas_by_events(db_session, days=1, as_of=now + timedelta(minutes=1), limit=500)
    by_arena = {r["arena_id"]: r for r in top}
    assert by_arena[arena_ids[1]]["events"] == 2 and by_arena[arena_ids[0]]["events"] == 1


async def test_comparable_since_is_first_new_format_row_or_env(db_session, monkeypatch) -> None:
    """Ревью #7: граница ряда не захардкожена — первая строка с dedup_key или явный env."""
    at = datetime(2020, 1, 2, 12, 0, tzinfo=timezone.utc)
    await _insert_event(db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor=telegram_actor_hash(1), at=at)
    await _insert_event(db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor="legacy-day-hash",
                        at=at - timedelta(days=30), dedup=False)
    await db_session.flush()
    assert await metrics_comparable_since(db_session) == at
    monkeypatch.setenv("CATALOG_METRICS_COMPARABLE_SINCE", "2026-10-07")
    since = await metrics_comparable_since(db_session)
    assert since == datetime(2026, 10, 6, 21, 0, tzinfo=timezone.utc)  # полночь по Минску


async def test_demand_pulse_minsk_day_excludes_bots_and_splits_channels(db_session) -> None:
    """«Сегодня» — календарный день Минска; превью не актор; билет бота не намерение."""
    now = datetime.now(timezone.utc)
    as_of = now + timedelta(minutes=1)
    web_today = public_actor_hash(client_ip="203.0.113.10", user_agent="pulse-human")
    web_earlier = public_actor_hash(client_ip="203.0.113.12", user_agent="pulse-earlier")
    tg = telegram_actor_hash(424242)
    bot = public_actor_hash(client_ip="203.0.113.11", user_agent="pulse-bot")
    before = await get_catalog_demand_pulse(db_session, as_of=as_of)

    await _insert_event(
        db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor=web_today, at=now,
        payload='{"ua_class": "human"}',
    )
    await _insert_event(
        db_session, kind=KIND_MINIAPP_CATALOG_ENTRY, actor=tg, at=now, surface="miniapp_ice",
        payload='{"share_deeplink": true}',
    )
    await _insert_event(
        db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor=bot, at=now,
        payload='{"ua_class": "preview"}',
    )
    await _insert_event(
        db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor=web_earlier, at=now - timedelta(days=2),
        payload='{"ua_class": "human"}',
    )
    await _insert_event(
        db_session, kind=KIND_PUBLIC_CONTACT_CLICK, actor=web_today, at=now,
        payload='{"action": "tickets", "ua_class": "human"}',
    )
    await _insert_event(
        db_session, kind=KIND_PUBLIC_CONTACT_CLICK, actor=bot, at=now,
        payload='{"action": "tickets", "ua_class": "preview"}',
    )
    await db_session.execute(
        text(
            """
            INSERT INTO client_share_events (kind, occurred_at, payload)
            VALUES ('place', :at, '{}'::jsonb)
            """
        ),
        {"at": now},
    )
    await db_session.flush()

    after = await get_catalog_demand_pulse(db_session, as_of=as_of)
    assert after["dau"] - before["dau"] == 2
    assert after["wau"] - before["wau"] == 3
    assert after["mau"] - before["mau"] == 3
    assert after["web_actors_7d"] - before["web_actors_7d"] == 2
    assert after["telegram_actors_7d"] - before["telegram_actors_7d"] == 1
    assert after["tickets_intent_actors_7d"] - before["tickets_intent_actors_7d"] == 1
    assert after["share_tap_7d"] - before["share_tap_7d"] == 1
    assert after["share_open_7d"] - before["share_open_7d"] == 1
    assert after["web_actors_7d"] + after["telegram_actors_7d"] == after["wau"]


# --- ретеншн ------------------------------------------------------------------------------------


async def test_retention_purge_in_ttl_tick(db_session) -> None:
    """События старше 400 дней удаляет TTL-цикл (run_ice_scrape_ttl_loop → run_ttl_tick)."""
    now = datetime.now(timezone.utc)
    await _insert_event(db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor="old-actor", at=now - timedelta(days=401),
                        dedup=False)
    await _insert_event(db_session, kind=KIND_PUBLIC_PAGE_VIEW, actor="fresh-actor", at=now - timedelta(days=399),
                        dedup=False)
    await db_session.flush()
    _stats, deleted = await run_ttl_tick(db_session, now=now)
    assert deleted >= 1
    left = (
        await db_session.execute(
            text("SELECT actor_hash FROM catalog_consumer_events WHERE actor_hash IN ('old-actor', 'fresh-actor')")
        )
    ).scalars().all()
    assert left == ["fresh-actor"]
    assert await purge_old_catalog_consumer_events(db_session, now=now) == 0


def test_ttl_loop_uses_tick() -> None:
    import inspect

    from src.ingestion import loop

    assert "run_ttl_tick" in inspect.getsource(loop.run_ice_scrape_ttl_loop)
