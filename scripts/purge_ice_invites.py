"""Удалить приглашения на каток старше N дней. Ответы уходят каскадом.

По умолчанию dry-run: печатает, сколько строк старше ``--days`` (90), и ничего
не удаляет. ``--apply`` пишет в локальную ``trainer_crm_test``. Облачная база —
только вместе с ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/purge_ice_invites.py
  PYTHONPATH=. python scripts/purge_ice_invites.py --apply
  PYTHONPATH=. python scripts/purge_ice_invites.py --apply --days 90 --i-know-this-is-prod
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.load_minsk_arena_cards import (  # noqa: E402
    assert_local_database_url,
    async_database_url,
    resolve_database_url,
)
from src.shared.ops_db_guard import (  # noqa: E402
    ProdDatabaseError,
    add_i_know_this_is_prod_argument,
    warn_prod_ack,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Удалить строки (иначе — только посчитать).")
    parser.add_argument("--days", type=int, default=90, help="Старше стольких дней. По умолчанию 90.")
    parser.add_argument(
        "--allow-local-dev-db",
        action="store_true",
        help="Разрешить --apply в локальную базу trainer_crm (облако по-прежнему запрещено).",
    )
    add_i_know_this_is_prod_argument(parser)
    return parser


async def _run(db_url: str, *, apply: bool, days: int) -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    engine = create_async_engine(async_database_url(db_url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            count = int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM ice_invites WHERE created_at < :cutoff"),
                        {"cutoff": cutoff},
                    )
                ).scalar_one()
            )
            print(f"Приглашений старше {days} дней: {count}")
            if not apply:
                print("\nDry-run: ничего не удалено. Добавьте --apply.")
                return 0
            result = await session.execute(
                text("DELETE FROM ice_invites WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            await session.commit()
            print(f"Удалено приглашений: {result.rowcount}")
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.days < 1:
        print("--days должен быть не меньше 1.", file=sys.stderr)
        return 2
    db_url = resolve_database_url()
    try:
        assert_local_database_url(
            db_url,
            apply=args.apply,
            allow_local_dev=args.allow_local_dev_db,
            allow_prod=args.i_know_this_is_prod,
        )
    except ProdDatabaseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.i_know_this_is_prod:
        warn_prod_ack()
    return asyncio.run(_run(db_url, apply=args.apply, days=args.days))


if __name__ == "__main__":
    raise SystemExit(main())
