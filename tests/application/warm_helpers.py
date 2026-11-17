"""Заготовки тестов прогрева посетителей (TASK-428): катки, клиенты, подписки, сеансы, визиты в каталог."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta

from sqlalchemy import text

from src.ingestion.hockey_sources import MINSK_TZ

ANNA, BORIS, VERA = 9428001, 9428002, 9428003
_seq = itertools.count(1)


def at(hour: int, minute: int = 0, *, day: int = 19, month: int = 11, year: int = 2026) -> datetime:
    """Момент по Минску. 19.11.2026 — четверг."""
    return datetime(year, month, day, hour, minute, tzinfo=MINSK_TZ)


async def seed_arena(db, name: str = "Чижовка-арена") -> int:
    n = next(_seq)
    city = (
        await db.execute(
            text("""
                INSERT INTO cities (name, country, price_group, is_active, sort_order)
                VALUES (:name, 'BY', 'default', true, 0) RETURNING id
                """),
            {"name": f"Warm City {n}"},
        )
    ).scalar_one()
    arena = (
        await db.execute(
            text("""
                INSERT INTO arenas (city_id, name, latitude, longitude, is_active, is_confirmed, venue_type)
                VALUES (:cid, :name, 53.9, 27.5, true, true, 'ice') RETURNING id
                """),
            {"cid": city, "name": name},
        )
    ).scalar_one()
    await db.execute(
        text("""
            INSERT INTO arena_profiles (arena_id, city_id, slug, timezone, status)
            VALUES (:aid, :cid, :slug, 'Europe/Minsk', 'published')
            """),
        {"aid": arena, "cid": city, "slug": f"warm-{arena}"},
    )
    return int(arena)


async def seed_client(db, telegram_id: int) -> int:
    await db.execute(
        text("INSERT INTO client_sessions (telegram_id, state) VALUES (:t, 'idle') ON CONFLICT DO NOTHING"),
        {"t": telegram_id},
    )
    row = (await db.execute(text("SELECT id FROM clients WHERE telegram_id = :t"), {"t": telegram_id})).first()
    if row:
        return int(row[0])
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO clients (first_name, telegram_id, is_sandbox) VALUES ('Гость', :t, false) RETURNING id"
                ),
                {"t": telegram_id},
            )
        ).scalar_one()
    )


async def seed_watch(
    db, telegram_id: int, arena_id: int, *, created_at: datetime, kind: str = "sessions", active: bool = True
) -> int:
    client_id = await seed_client(db, telegram_id)
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO client_ice_watches
                        (client_id, telegram_id, arena_id, watch_kind, filter_json, active, created_at)
                    VALUES (:c, :t, :a, :k, '{"when": "any", "intent": "skate"}', :act, :at) RETURNING id
                    """),
                {"c": client_id, "t": telegram_id, "a": arena_id, "k": kind, "act": active, "at": created_at},
            )
        ).scalar_one()
    )


async def seed_session(db, arena_id: int, starts: datetime, *, status: str = "active") -> int:
    local = starts.astimezone(MINSK_TZ)
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO ice_sessions (
                        arena_id, kind, status, starts_at_utc, ends_at_utc,
                        starts_at_local, ends_at_local, local_date, schedule_basis, currency_code
                    )
                    VALUES (:a, 'public_skate', :st, :s, :e, :sl, :el, :ld, 'live', 'BYN') RETURNING id
                    """),
                {
                    "a": arena_id,
                    "st": status,
                    "s": starts,
                    "e": starts + timedelta(hours=1),
                    "sl": local.time(),
                    "el": (local + timedelta(hours=1)).time(),
                    "ld": local.date(),
                },
            )
        ).scalar_one()
    )


async def seed_delivery(db, watch_id: int, at_: datetime, *, ok: bool = True) -> None:
    row = (
        await db.execute(text("SELECT client_id, arena_id FROM client_ice_watches WHERE id = :w"), {"w": watch_id})
    ).one()
    await db.execute(
        text("""
            INSERT INTO client_ice_watch_deliveries (watch_id, client_id, arena_id, attempted_at, ok)
            VALUES (:w, :c, :a, :at, :ok)
            """),
        {"w": watch_id, "c": row.client_id, "a": row.arena_id, "at": at_, "ok": ok},
    )


async def seed_warm_notice(
    db,
    telegram_id: int,
    kind: str,
    sent_at: datetime | None,
    *,
    ref: str | None = None,
    created_at: datetime | None = None,
    failed: bool = False,
) -> None:
    await db.execute(
        text("""
            INSERT INTO warm_notices (telegram_id, kind, ref, sent_at, failed, created_at)
            VALUES (:t, :k, :r, :s, :f, COALESCE(:c, :s, now()))
            """),
        {"t": telegram_id, "k": kind, "r": ref or f"t{next(_seq)}", "s": sent_at, "f": failed, "c": created_at},
    )


async def seed_warm_prefs(db, telegram_id: int, *, opted_out_at=None, bot_blocked_at=None) -> None:
    await db.execute(
        text("""
            INSERT INTO warm_prefs (telegram_id, opted_out_at, bot_blocked_at) VALUES (:t, :o, :b)
            ON CONFLICT (telegram_id) DO UPDATE SET opted_out_at = :o, bot_blocked_at = :b
            """),
        {"t": telegram_id, "o": opted_out_at, "b": bot_blocked_at},
    )


async def seed_visit(db, actor_hash: str, when: datetime, *, arena_id: int | None = None) -> None:
    await db.execute(
        text("""
            INSERT INTO catalog_consumer_events (kind, surface, actor_hash, arena_id, occurred_at, payload)
            VALUES ('miniapp_catalog_entry', 'miniapp_arena', :h, :a, :w, '{}'::jsonb)
            """),
        {"h": actor_hash, "a": arena_id, "w": when},
    )
