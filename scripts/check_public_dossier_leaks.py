"""TASK-208 AC-1: public catalog must not expose dossier loader markers.

Scans every publicly visible arena through the same sanitization path as
``get_public_arena_card`` (district, opening_hours, schedule_mode_note).

Default: exit 0 when clean, 1 when any leak remains. Never writes.

Usage:
  DATABASE_URL=postgresql+asyncpg://trainer_crm:…@localhost/trainer_crm_test_t208 \\
    PYTHONPATH=. python scripts/check_public_dossier_leaks.py
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
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL
from src.shared.ops_db_guard import assert_database_url, async_database_url


async def _run() -> int:
    url = async_database_url(os.environ["DATABASE_URL"])
    assert_database_url(url, allow_prod=False)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    failures: list[str] = []
    async with factory() as session:
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
                )
            )
        ).mappings().all()
        for row in rows:
            aid = int(row["id"])
            ref = str(row["slug"] or aid)
            card = await get_public_arena_card(session, ref)
            if card is None:
                continue
            hits = public_payload_contains_dossier_leak(card)
            if hits:
                failures.append(f"arena_id={aid} slug={row['slug']}: " + "; ".join(hits))
    await engine.dispose()
    if failures:
        print("Dossier leak markers found in public payloads:", ", ".join(DOSSIER_LEAK_NEEDLES))
        for line in failures:
            print(line)
        return 1
    print(f"OK: {len(rows)} public arenas, no dossier leak markers in API card payloads.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="TASK-208: scan public arena cards for dossier leaks.")
    parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required")
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
