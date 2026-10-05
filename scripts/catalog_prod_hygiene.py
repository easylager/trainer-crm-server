"""One-off prod catalog hygiene (TASK-177, catalog audit 2026-10-05 §2).

Three steps, all in ONE transaction:

1. **Test arenas** — every arena whose name matches «тест/test» (``looks_like_test_arena_name``)
   and whose profile is not yet ``archived`` → profile ``archived``. ``arenas.is_active``
   is left alone: «Тестовая Арена 3» is a trainer's primary arena with slots and a
   booking; hiding it from the catalog must not break that trainer's schedule.
2. **Duplicates** — each reviewed pair in ``DUPLICATES`` (justification next to it):
   references are re-pointed to the canonical id (trainer links, slots, bookings,
   templates, groups, analytics rows), then the duplicate gets
   ``merged_into_arena_id = canonical`` (old ``/p/`` URLs answer 301), ``is_active = false``
   and profile ``archived``. A pair is refused if the duplicate owns ice data
   (parser job, sessions, scrape runs, schedule presets) — that needs a human decision.
   The duplicate's expected name is checked first so a wrong id never merges.
3. **Past sessions** — ``active`` ice_sessions that ended more than a day ago →
   ``expired`` (same rule as the TTL loop, ``src/ingestion/ttl.py``).

RU (Moscow, SPb) is hidden by config, not by this script: ``ICE_DISCOVERY_COUNTRIES=BY``.

Default is a dry-run inside a READ ONLY transaction (nothing can be written). Steps 2–3
need migration ``0217_catalog_prod_hygiene``; the dry-run reports it if missing, apply
refuses.

Usage (prod, values from Railway, never committed):
  DATABASE_URL=<DATABASE_PUBLIC_URL> PYTHONPATH=. python scripts/catalog_prod_hygiene.py --i-know-this-is-prod
  DATABASE_URL=<DATABASE_PUBLIC_URL> PYTHONPATH=. python scripts/catalog_prod_hygiene.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from src.application.arena_profile import looks_like_test_arena_name  # noqa: E402
# Same rule as src/ingestion/ttl.py (importing it pulls the whole bot stack + Settings);
# tests/scripts/test_catalog_prod_hygiene_script.py pins the two together.
SESSION_EXPIRE_AFTER = timedelta(days=1)
from src.shared.ops_db_guard import (  # noqa: E402
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    normalize_db_url,
    warn_prod_ack,
)


@dataclass(frozen=True)
class Duplicate:
    dup_id: int
    canonical_id: int
    dup_name_contains: str
    reason: str


# Reviewed against prod 2026-10-05 (read-only). Order matters only for readability.
DUPLICATES: tuple[Duplicate, ...] = (
    Duplicate(
        197, 7, "Даймонд",
        "«Даймонд сити» — trainer-created (trainer 33), never confirmed, no coords; same address "
        "(Щомыслицкий с/с 32/4) as «ТЦ DiaMond city» #7 which has the parser and 121 sessions. "
        "Trainer 33 is already linked to #3; their #197 link moves to #7.",
    ),
    Duplicate(
        202, 3, "Замок",
        "«Замок» — trainer-created (trainer 54), already rejected (is_active=false); "
        "address «Победителей 65» and coords ~40 m from «ТЦ Замок» #3 (parser, 243 sessions).",
    ),
    Duplicate(
        21, 22, "Брестский ледовый",
        "Same name and address (ул. Московская, 151) as Брест #22, but filed under city Жодино; "
        "inactive, no data. Wrong-city import row.",
    ),
    Duplicate(
        39, 22, "Крытый каток",
        "«Крытый каток», п. Озерный — address «ул. Московская, 151» and coords identical to #21, "
        "i.e. the Brest palace #22; parser census lists no Ozerny rink. Profile archived 2026-09-17.",
    ),
    Duplicate(
        17, 19, "Спортивно-зрелищный",
        "Same name and address (ул. К. Заслонова, 25) and coords within ~20 m of Солигорск #19 "
        "(parser), but filed under city Молодечно; inactive, no data.",
    ),
)

# FK columns (ON DELETE SET NULL) that simply follow the arena to its canonical id.
_REPOINT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("slots", "arena_id"),
    ("bookings", "arena_id"),
    ("trainer_schedule_templates", "arena_id"),
    ("trainers", "primary_arena_id"),
    ("training_groups", "arena_id"),
    ("collectives", "primary_arena_id"),
    ("collective_sessions", "arena_id"),
    ("client_sessions", "selected_arena_id"),
    ("catalog_consumer_events", "arena_id"),
    ("client_share_events", "arena_id"),
)
# CASCADE-owned ice data: a duplicate that has any of it is not merged automatically.
_BLOCKING_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ice_parser_jobs", "arena_id"),
    ("ice_sessions", "arena_id"),
    ("ice_scrape_runs", "arena_id"),
    ("arena_schedule_presets", "arena_id"),
)


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("Set DATABASE_URL_SYNC or DATABASE_URL")
    return normalize_db_url(raw)


async def _scalar(session: AsyncSession, sql: str, params: dict | None = None):
    return (await session.execute(text(sql), params or {})).scalar()


async def _has_hygiene_migration(session: AsyncSession) -> bool:
    col = await _scalar(
        session,
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'arenas' AND column_name = 'merged_into_arena_id'",
    )
    ck = await _scalar(
        session,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_ice_sessions_status'",
    )
    return bool(col) and "expired" in str(ck or "")


async def step_test_arenas(session: AsyncSession, *, apply: bool) -> list[str]:
    rows = (
        await session.execute(
            text(
                """
                SELECT a.id, a.name, c.name, c.country, p.status, a.is_active, a.is_confirmed
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                ORDER BY a.id
                """
            )
        )
    ).fetchall()
    out: list[str] = []
    for aid, name, city, country, status, active, confirmed in rows:
        if not looks_like_test_arena_name(name) or status == "archived":
            continue
        out.append(
            f"  test  #{aid} {name!r} ({city}, {country}; is_active={active}, is_confirmed={confirmed}) "
            f"profile {status!r} -> 'archived'"
        )
        if apply:
            if status is None:
                raise SystemExit(f"#{aid} has no arena_profiles row — create it in admin first")
            await session.execute(
                text("UPDATE arena_profiles SET status = 'archived', updated_at = now() WHERE arena_id = :id"),
                {"id": aid},
            )
    return out


async def step_duplicates(session: AsyncSession, *, apply: bool, migrated: bool) -> list[str]:
    out: list[str] = []
    for d in DUPLICATES:
        dup = (
            await session.execute(
                text(
                    "SELECT a.name, a.is_active, p.status FROM arenas a "
                    "LEFT JOIN arena_profiles p ON p.arena_id = a.id WHERE a.id = :id"
                ),
                {"id": d.dup_id},
            )
        ).fetchone()
        canon = (
            await session.execute(text("SELECT name, is_active FROM arenas WHERE id = :id"), {"id": d.canonical_id})
        ).fetchone()
        head = f"  dup   #{d.dup_id} -> #{d.canonical_id}"
        if dup is None or canon is None:
            out.append(f"{head}: SKIP — arena missing (dup={dup is not None}, canonical={canon is not None})")
            continue
        if d.dup_name_contains.lower() not in str(dup[0]).lower():
            out.append(f"{head}: SKIP — name {dup[0]!r} does not contain {d.dup_name_contains!r}")
            continue
        if not canon[1]:
            out.append(f"{head}: SKIP — canonical {canon[0]!r} is inactive")
            continue
        blocking = []
        for table, col in _BLOCKING_COLUMNS:
            n = await _scalar(session, f"SELECT COUNT(*) FROM {table} WHERE {col} = :id", {"id": d.dup_id})
            if n:
                blocking.append(f"{table}={n}")
        if blocking:
            out.append(f"{head}: SKIP — duplicate owns ice data ({', '.join(blocking)}); merge by hand")
            continue
        merged_now = (
            await _scalar(session, "SELECT merged_into_arena_id FROM arenas WHERE id = :id", {"id": d.dup_id})
            if migrated
            else None
        )
        moves = []
        for table, col in _REPOINT_COLUMNS:
            n = await _scalar(session, f"SELECT COUNT(*) FROM {table} WHERE {col} = :id", {"id": d.dup_id})
            if n:
                moves.append(f"{table}.{col}={n}")
        links = (
            await session.execute(
                text("SELECT trainer_id FROM trainer_arenas WHERE arena_id = :id ORDER BY trainer_id"),
                {"id": d.dup_id},
            )
        ).scalars().all()
        if links:
            moves.append("trainer_arenas trainers=" + ",".join(str(t) for t in links))
        out.append(
            f"{head}: {dup[0]!r} -> {canon[0]!r}\n"
            f"        is_active {dup[1]} -> False; profile {dup[2]!r} -> 'archived'; "
            f"merged_into_arena_id {merged_now} -> {d.canonical_id}"
            + ("" if migrated else " (column pending migration 0217)")
            + f"\n        re-point: {', '.join(moves) or 'nothing'}"
            + f"\n        why: {d.reason}"
        )
        if not apply:
            continue
        params = {"dup": d.dup_id, "canon": d.canonical_id}
        await session.execute(
            text(
                "INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) "
                "SELECT trainer_id, :canon, is_public FROM trainer_arenas WHERE arena_id = :dup "
                "ON CONFLICT (trainer_id, arena_id) DO NOTHING"
            ),
            params,
        )
        await session.execute(text("DELETE FROM trainer_arenas WHERE arena_id = :dup"), params)
        for table, col in _REPOINT_COLUMNS:
            await session.execute(text(f"UPDATE {table} SET {col} = :canon WHERE {col} = :dup"), params)
        await session.execute(
            text("UPDATE arenas SET merged_into_arena_id = :canon, is_active = false WHERE id = :dup"), params
        )
        await session.execute(
            text("UPDATE arena_profiles SET status = 'archived', updated_at = now() WHERE arena_id = :dup"),
            params,
        )
    return out


async def step_past_sessions(session: AsyncSession, *, apply: bool, now: datetime) -> list[str]:
    cutoff = now - SESSION_EXPIRE_AFTER
    rows = (
        await session.execute(
            text(
                """
                SELECT c.country, COUNT(*)::int, MIN(s.ends_at_utc), MAX(s.ends_at_utc)
                FROM ice_sessions s
                JOIN arenas a ON a.id = s.arena_id
                JOIN cities c ON c.id = a.city_id
                WHERE s.status = 'active' AND s.ends_at_utc < :cutoff
                GROUP BY c.country ORDER BY c.country
                """
            ),
            {"cutoff": cutoff},
        )
    ).fetchall()
    out = [
        f"  sess  {country}: {n} active sessions ended before {cutoff:%Y-%m-%d %H:%M}Z "
        f"(oldest end {lo:%Y-%m-%d}, newest {hi:%Y-%m-%d}) status 'active' -> 'expired'"
        for country, n, lo, hi in rows
    ]
    if apply:
        await session.execute(
            text("UPDATE ice_sessions SET status = 'expired' WHERE status = 'active' AND ends_at_utc < :cutoff"),
            {"cutoff": cutoff},
        )
    return out


async def run(*, apply: bool, i_know_this_is_prod: bool) -> None:
    url = _db_url()
    assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
    if i_know_this_is_prod:
        warn_prod_ack()
    engine = create_async_engine(async_database_url(url))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        async with Session() as session:
            if not apply:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            migrated = await _has_hygiene_migration(session)
            if apply and not migrated:
                raise SystemExit("Migration 0217_catalog_prod_hygiene is not applied — run alembic first.")
            mode = "APPLY" if apply else "DRY-RUN (read-only transaction)"
            print(f"catalog_prod_hygiene {mode} at {now:%Y-%m-%d %H:%M}Z; migration 0217 present: {migrated}")
            print("\n[1] test arenas")
            print("\n".join(await step_test_arenas(session, apply=apply)) or "  nothing to do")
            print("\n[2] duplicates")
            print("\n".join(await step_duplicates(session, apply=apply, migrated=migrated)) or "  nothing to do")
            print("\n[3] past active sessions")
            print("\n".join(await step_past_sessions(session, apply=apply, now=now)) or "  nothing to do")
            if apply:
                await session.commit()
                print("\nCommitted.")
            else:
                await session.rollback()
                print("\nDry-run only — nothing written. Re-run with --apply to write.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Write to the database (default: dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, i_know_this_is_prod=args.i_know_this_is_prod))


if __name__ == "__main__":
    main()
