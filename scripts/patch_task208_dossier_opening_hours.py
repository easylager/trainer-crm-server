"""TASK-208: fix three prod profiles with dossier text in opening_hours (and district 29).

Recomputes values from ``data/arena-cards/*.md`` via ``load_minsk_arena_cards.parse_dossier``.
Default dry-run inside a transaction (rolls back). Prod apply needs ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/patch_task208_dossier_opening_hours.py
  DATABASE_URL="$DATABASE_PUBLIC_URL" PYTHONPATH=. \\
    python scripts/patch_task208_dossier_opening_hours.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import importlib.util

from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    warn_prod_ack,
)
from src.shared.config import Settings

CARDS = ROOT / "data" / "arena-cards"
_LOADER = ROOT / "scripts" / "load_minsk_arena_cards.py"


def _loader():
    spec = importlib.util.spec_from_file_location("load_minsk_arena_cards", _LOADER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Prod 2026-10-07 (TASK-208)
PATCHES: tuple[tuple[int, str], ...] = (
    (29, "vitebsk-ds.md"),
    (2, "minsk-minskarena.md"),
    (6, "minsk-chizhovka.md"),
)


def _target_fields(path: Path) -> dict:
    card = _loader().parse_dossier(path)
    return {
        "opening_hours": card.opening_hours,
        "district": card.district,
    }


async def run(*, apply: bool, allow_prod: bool) -> None:
    url = async_database_url(Settings().database_url)
    assert_database_url(url, apply=apply, allow_prod=allow_prod)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for arena_id, filename in PATCHES:
            path = CARDS / filename
            if not path.is_file():
                raise SystemExit(f"missing dossier {path}")
            desired = _target_fields(path)
            row = (
                await session.execute(
                    text(
                        """
                        SELECT p.district, p.opening_hours
                        FROM arena_profiles p
                        WHERE p.arena_id = :id
                        """
                    ),
                    {"id": arena_id},
                )
            ).mappings().first()
            if not row:
                raise SystemExit(f"arena_id={arena_id}: no arena_profiles row")
            before = {
                "district": row["district"],
                "opening_hours": row["opening_hours"],
            }
            print(f"--- arena_id={arena_id} ({filename}) ---")
            print("before:", json.dumps(before, ensure_ascii=False, sort_keys=True))
            print("after: ", json.dumps(desired, ensure_ascii=False, sort_keys=True))
            if apply:
                await session.execute(
                    text(
                        """
                        UPDATE arena_profiles
                        SET district = :district,
                            opening_hours = CAST(:hours AS jsonb),
                            updated_at = NOW()
                        WHERE arena_id = :id
                        """
                    ),
                    {
                        "id": arena_id,
                        "district": desired["district"],
                        "hours": json.dumps(desired["opening_hours"])
                        if desired["opening_hours"] is not None
                        else None,
                    },
                )
        if apply:
            await session.commit()
            print("committed.")
        else:
            await session.rollback()
            print("dry-run (rolled back).")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="TASK-208 prod profile patch (opening_hours / district).")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    allow_prod = bool(args.i_know_this_is_prod)
    if allow_prod:
        warn_prod_ack()
    asyncio.run(run(apply=args.apply, allow_prod=allow_prod))


if __name__ == "__main__":
    main()
