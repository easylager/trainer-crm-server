"""TASK-208 AC-1: public catalog must not expose dossier loader markers.

Scans every publicly visible arena through the same sanitization path as
``get_public_arena_card`` (district, opening_hours, schedule_mode_note).

Default: exit 0 when clean, 1 when any leak remains. Never writes.

Usage:
  DATABASE_URL=postgresql+asyncpg://trainer_crm:…@localhost/trainer_crm_test_t208 \\
    PYTHONPATH=. python scripts/check_public_dossier_leaks.py
  DATABASE_URL="$DATABASE_PUBLIC_URL" PYTHONPATH=. \\
    python scripts/check_public_dossier_leaks.py --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application.arena_public_use_cases import get_public_arena_card
from src.shared.dossier_public_text import DOSSIER_LEAK_NEEDLES, public_payload_contains_dossier_leak
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    warn_prod_ack,
)


async def _scan(session) -> tuple[int, list[str], list[int]]:
    rows = (
        await session.execute(
            text(
                f"""
                SELECT a.id, p.slug, a.name
                FROM arenas a
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                JOIN cities c ON c.id = a.city_id
                WHERE {PUBLIC_ARENA_VISIBLE_SQL}
                ORDER BY a.id
                """
            ),
            public_scope_params(),
        )
    ).mappings().all()
    failures: list[str] = []
    checked: list[int] = []
    for row in rows:
        aid = int(row["id"])
        ref = str(row["slug"] or aid)
        card = await get_public_arena_card(session, ref)
        if card is None:
            continue
        checked.append(aid)
        hits = public_payload_contains_dossier_leak(card)
        if hits:
            failures.append(f"arena_id={aid} slug={row['slug']}: " + "; ".join(hits))
    return len(rows), failures, checked


async def _run(*, allow_prod: bool) -> int:
    url = async_database_url(os.environ["DATABASE_URL"])
    assert_database_url(url, apply=False, allow_prod=allow_prod)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        scanned, failures, _checked = await _scan(session)
    await engine.dispose()
    if failures:
        print("Dossier leak markers found in public payloads:", ", ".join(DOSSIER_LEAK_NEEDLES))
        for line in failures:
            print(line)
        return 1
    print(f"OK: {scanned} public arenas, no dossier leak markers in API card payloads.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="TASK-208: scan public arena cards for dossier leaks.")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required")
    allow_prod = bool(args.i_know_this_is_prod)
    if allow_prod:
        warn_prod_ack()
    raise SystemExit(asyncio.run(_run(allow_prod=allow_prod)))


if __name__ == "__main__":
    main()
