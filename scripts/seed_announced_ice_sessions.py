"""Seed CMS ice sessions as admin+manual (no online Buy) without wiping siblings.

Use AFTER the publish adopt + iceRowCta changes land. source_id must be ``admin``
(never null — the next parser run would delete null rows). schedule_basis=manual,
external_url null → Mini App shows «Билетов пока нет». When ABWS later emits the
same slot, publish adopts the row (live + saleframe url) and Buy appears.

Preview (no DB):
  PYTHONPATH=. python scripts/seed_announced_ice_sessions.py \\
    data/announced-schedules/minsk-speed-oval-weekend-2026-11-07.json --preview

Apply:
  PYTHONPATH=. python scripts/seed_announced_ice_sessions.py <file> --apply --i-know-this-is-prod
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

from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    warn_prod_ack,
)


def preview(spec: dict) -> None:
    defaults = spec.get("defaults") or {}
    print(f"arena_id={spec.get('arena_id')} source_id=admin schedule_basis=manual external_url=null")
    for row in spec.get("sessions") or []:
        merged = {**defaults, **row}
        print(
            f"  {merged.get('date')} {merged.get('start')} "
            f"adult={merged.get('price_adult')} child={merged.get('price_child')} "
            f"rental={merged.get('price_rental')} hall={merged.get('hall')!r} "
            f"dur={merged.get('duration_minutes')}"
        )
    print(f"sessions={len(spec.get('sessions') or [])}")


async def apply(spec: dict) -> None:
    from src.application.admin_announced_ice_sessions import upsert_admin_announced_sessions
    from src.infrastructure.db.session import async_session_factory

    async with async_session_factory() as session:
        counts = await upsert_admin_announced_sessions(session, spec)
        await session.commit()
    print(
        "inserted={inserted} updated={updated} "
        "skipped_live={skipped_live} skipped_same={skipped_same}".format(**counts)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("--preview", action="store_true", help="print spec only, no database")
    ap.add_argument("--apply", action="store_true", help="write to DATABASE_URL")
    add_i_know_this_is_prod_argument(ap)
    args = ap.parse_args()
    spec = json.loads(args.file.read_text(encoding="utf-8"))
    if args.preview or not args.apply:
        preview(spec)
        if not args.apply:
            return
    from src.shared.config import Settings

    url = Settings().database_url
    assert_database_url(url, apply=True, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        assert_railway_target_database(url)
        warn_prod_ack()
    asyncio.run(apply(spec))


if __name__ == "__main__":
    main()
