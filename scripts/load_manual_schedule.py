"""Load a hand-entered weekly schedule for an arena through the normal ingest pipeline.

For arenas without a working parser (job ``manual_schedule_v1``): the schedule comes from a
poster/post and lives in ``data/manual-schedules/<arena>.json``. The file goes through the
same normalizer → validator → publisher as parsed sources, so TTL, diff and watch delivery
behave identically. A successful non-empty run replaces the arena's future sessions except
``admin`` / ``etalon_*``; an empty file erases nothing.

Dry run (default, no DB): prints what would be published.
  PYTHONPATH=. python scripts/load_manual_schedule.py data/manual-schedules/zhlobin-metallurg.json
Apply (prod, Railway public DB URL in DATABASE_URL):
  PYTHONPATH=. python scripts/load_manual_schedule.py <file> --apply --i-know-this-is-prod
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

from src.application.manual_schedule_publish import preview_spec, publish_spec
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    warn_prod_ack,
)


def dry_run(spec: dict) -> None:
    drafts = preview_spec(spec)
    for d in drafts:
        print(
            f"{d.local_date} {d.starts_at_local:%H:%M}-{d.ends_at_local:%H:%M} {d.kind} "
            f"adult={d.price_adult_minor} child={d.price_child_minor} rental={d.price_rental_minor} "
            f"{d.currency_code} label={d.session_label!r} cap={d.capacity_note!r}"
        )
    print(f"drafts={len(drafts)}")


async def apply(spec: dict) -> None:
    for r in await publish_spec(spec):
        print(
            f"arena_id={r.arena_id} status={r.status} published={r.slot_count} "
            f"dropped={r.slots_dropped} code={r.error_code or ''} error={r.error_message or ''}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", type=Path)
    ap.add_argument("--apply", action="store_true", help="publish to the database in DATABASE_URL")
    add_i_know_this_is_prod_argument(ap)
    args = ap.parse_args()
    spec = json.loads(args.file.read_text(encoding="utf-8"))
    if not args.apply:
        dry_run(spec)
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
