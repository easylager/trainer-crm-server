"""Apply mass-access hours + rental copy for arena_id=12 (лыжероллерная трасса).

Data: data/arena-cards/lyzheroller-trassa-profile.json

Usage:
  PYTHONPATH=. python scripts/apply_lyzheroller_mass_access_profile.py
  PYTHONPATH=. python scripts/apply_lyzheroller_mass_access_profile.py --apply --i-know-this-is-prod
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.arena_profile import apply_admin_arena_profile_patch
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    normalize_db_url,
    warn_prod_ack,
)

PROFILE_PATH = ROOT / "data" / "arena-cards" / "lyzheroller-trassa-profile.json"


def _load_profile() -> dict:
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    arena_id = int(data["arena_id"])
    return {
        "arena_id": arena_id,
        "venue_type": data["venue_type"],
        "patch": {
            "website_url": data["website_url"],
            "opening_hours": data["opening_hours"],
            "amenities": data["amenities"],
            "short_description": data["short_description"],
        },
    }


async def run(*, apply: bool, i_know_this_is_prod: bool) -> None:
    spec = _load_profile()
    url = normalize_db_url(os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"])
    assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
    if i_know_this_is_prod:
        warn_prod_ack()
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    engine = create_async_engine(url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    aid = spec["arena_id"]
    async with Session() as session:
        row = (
            await session.execute(
                text("SELECT name FROM arenas WHERE id = :id"),
                {"id": aid},
            )
        ).fetchone()
        if not row:
            raise SystemExit(f"arena_id={aid} not found")
        print(f"arena_id={aid} {row[0]!r}")
        print("venue_type ->", spec["venue_type"])
        print("profile patch keys:", list(spec["patch"]))
        if apply:
            await session.execute(
                text("UPDATE arenas SET venue_type = :vt WHERE id = :id"),
                {"vt": spec["venue_type"], "id": aid},
            )
            await apply_admin_arena_profile_patch(session, aid, spec["patch"])
            await session.commit()
            print("applied.")
        else:
            print("dry-run; pass --apply to write")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, i_know_this_is_prod=args.i_know_this_is_prod))


if __name__ == "__main__":
    main()
