"""IndexNow: разово отправить все URL из sitemap.xml (первичная засылка после включения).

Берёт те же URL, что отдаёт /sitemap.xml (общий предикат видимости), и шлёт их
в api.indexnow.org пачками по 10000. Нужны INDEXNOW_ENABLED=true и INDEXNOW_KEY.
Только читает БД. Прод (только SELECT) — с ``--i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/indexnow_submit_sitemap.py --dry-run
  PYTHONPATH=. INDEXNOW_ENABLED=true INDEXNOW_KEY=<32 hex> python scripts/indexnow_submit_sitemap.py
  PYTHONPATH=. python scripts/indexnow_submit_sitemap.py --i-know-this-is-prod
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.load_minsk_arena_cards import async_database_url, resolve_database_url  # noqa: E402
from src.application.indexnow import active_key, fetch_sitemap_urls, submit_urls  # noqa: E402
from src.shared.ops_db_guard import (  # noqa: E402
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Только напечатать число URL и первые из них.")
    parser.add_argument("--show", type=int, default=10, help="Сколько первых URL печатать при --dry-run.")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()

    db_url = resolve_database_url()
    assert_database_url(db_url, apply=False, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        warn_prod_ack()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(async_database_url(db_url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            urls = await fetch_sitemap_urls(session)
    finally:
        await engine.dispose()

    if args.dry_run:
        print(f"URL в sitemap: {len(urls)}")
        for url in urls[: max(args.show, 0)]:
            print(url)
        return 0

    if active_key() is None:
        print("IndexNow выключен: нужны INDEXNOW_ENABLED=true и INDEXNOW_KEY (32 hex).", file=sys.stderr)
        return 2
    accepted = await submit_urls(urls, dedup=False)
    print(f"Принято IndexNow: {accepted} из {len(urls)}")
    return 0 if accepted == len(urls) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
