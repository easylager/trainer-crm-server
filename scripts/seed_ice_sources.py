"""First fill of the admin «Источники расписаний» list (see src/application/ice_sources_seed.py).

Dry run by default: prints what would be written.
  PYTHONPATH=. python scripts/seed_ice_sources.py
Prod (after migration 0276 is deployed):
  bash scripts/run_ice_ingest_prod_local.sh scripts/seed_ice_sources.py --apply --i-know-this-is-prod
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

OVERRIDES_FILE = ROOT / "data" / "ice-sources-overrides.json"
PARSER_STATUS_FILE = ROOT / "data" / "ice-parser-status.json"


def _registry_urls() -> dict[str, str]:
    """arena_id → source link from the parser registry, for rinks whose card has no website."""
    raw = json.loads(PARSER_STATUS_FILE.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else next((v for v in raw.values() if isinstance(v, list)), [])
    return {str(r["arena_id"]): r["source"] for r in rows if isinstance(r, dict) and r.get("arena_id") and r.get("source")}


async def _run(apply: bool) -> None:
    from src.application.ice_sources_seed import apply_seed, plan_seed
    from src.infrastructure.db.session import async_session_factory

    overrides = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8")).get("overrides", {})
    async with async_session_factory() as session:
        plan = await plan_seed(session, overrides, _registry_urls())
        for p in plan:
            print(f"{p['origin']:8} {p['arena_id']:>4} {p['city']} / {p['name'][:28]:28} {p['fetch_mode']:7} {p['source_url'] or '-'}")
        print(f"rows: {len(plan)}")
        if apply:
            print(f"written: {await apply_seed(session, plan)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(ap)
    args = ap.parse_args()
    from src.shared.config import Settings

    url = Settings().database_url
    assert_database_url(url, apply=args.apply, allow_prod=args.i_know_this_is_prod)
    if args.apply and args.i_know_this_is_prod:
        assert_railway_target_database(url)
        warn_prod_ack()
    asyncio.run(_run(args.apply))


if __name__ == "__main__":
    main()
