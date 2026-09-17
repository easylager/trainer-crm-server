"""Archive three BY arena_profiles rows that would otherwise surface as bare cards on the
Ice Discovery vitrine once the skate-intent listing stops requiring a future session
(fix/ice-catalog-show-all-arenas — the intent=skate filter previously hid every arena with
no live session; lifting it means data-quality rows that were only hidden as a side effect
now need an explicit exclusion).

Each id and reason (owner-approved 2026-09-17):

- arena_id=12 «Лыжероллерная трасса» — a roller-ski track, not ice. Not a schedule problem,
  a category error; it should stay a plain trainer-workplace row, never on the ice vitrine.
- arena_id=39 «Крытый каток» — coordinates ~1.3km from arena_id=22 (Брестский ЛДС); looks
  like a duplicate catalog entry for the same building, not two rinks.
- arena_id=199 «Тестовая Арена 2» — name and lack of any real profile data mark this as a
  leftover test fixture that leaked into the production arenas table.

Sets ``arena_profiles.status = 'archived'`` via ``apply_admin_arena_profile_patch`` (creates
the row first if somehow missing). Does not touch ``arenas.is_active``/``is_confirmed`` —
those govern the trainer-workplace picker and other subsystems, out of scope here.

Default is dry-run. Cloud/Railway requires ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/archive_stale_arena_profiles.py
  PYTHONPATH=. python scripts/archive_stale_arena_profiles.py --apply --i-know-this-is-prod
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.arena_profile import (
    ARENA_PROFILE_STATUS_ARCHIVED,
    apply_admin_arena_profile_patch,
)
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    normalize_db_url,
    warn_prod_ack,
)

ARENA_IDS_TO_ARCHIVE: tuple[int, ...] = (12, 39, 199)


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("Set DATABASE_URL_SYNC or DATABASE_URL")
    return normalize_db_url(raw)


async def run(*, apply: bool, i_know_this_is_prod: bool) -> None:
    url = _db_url()
    assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
    if i_know_this_is_prod:
        warn_prod_ack()

    async_url = url
    if async_url.startswith("postgresql://"):
        async_url = "postgresql+asyncpg://" + async_url[len("postgresql://") :]
    engine = create_async_engine(async_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    archived = 0
    already = 0
    async with Session() as session:
        for arena_id in ARENA_IDS_TO_ARCHIVE:
            row = (
                await session.execute(
                    text("SELECT name FROM arenas WHERE id = :id"),
                    {"id": arena_id},
                )
            ).fetchone()
            if row is None:
                print(f"  [skip] arena_id={arena_id} not found in arenas table")
                continue
            name = row[0]
            existing_status = (
                await session.execute(
                    text("SELECT status FROM arena_profiles WHERE arena_id = :id"),
                    {"id": arena_id},
                )
            ).fetchone()
            current = existing_status[0] if existing_status else None
            if current == ARENA_PROFILE_STATUS_ARCHIVED:
                already += 1
                print(f"  [already-archived] arena_id={arena_id} {name!r}")
                continue
            archived += 1
            flag = "apply" if apply else "dry-run"
            print(f"  [{flag}] arena_id={arena_id} {name!r} — status {current!r} -> archived")
            if apply:
                await apply_admin_arena_profile_patch(
                    session, arena_id, {"status": ARENA_PROFILE_STATUS_ARCHIVED}
                )
        if apply:
            await session.commit()
            print(f"\nArchived {archived} arena(s), {already} already archived.")
        else:
            print(f"\nDry-run only — {archived} arena(s) would be archived. Pass --apply to write.")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write to the database (default: dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, i_know_this_is_prod=args.i_know_this_is_prod))


if __name__ == "__main__":
    main()
