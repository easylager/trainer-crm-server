"""
One-off: Telegram notify trainers for ratings stored before notify_trainer_client_rating shipped.

trainer_ratings has no booking_id — booking is resolved from platform_audit (trainer.rated)
or the latest completed session for that trainer + client.

Usage:
  python -m scripts.backfill_trainer_rating_notifications --dry-run
  python -m scripts.backfill_trainer_rating_notifications
  python -m scripts.backfill_trainer_rating_notifications --rating-id 1

Env: .env with database_url, TELEGRAM_BOT_TOKEN_TRAINER, WEBAPP_BASE_URL (https for client card button).
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

from src.application.trainer_rating_notify import (
    load_stored_rating_row,
    notify_trainer_for_stored_rating,
)
from src.infrastructure.db import async_session_factory


async def main(rating_id: int | None, dry_run: bool) -> int:
    async with async_session_factory() as session:
        rows = await load_stored_rating_row(session, rating_id=rating_id)
        if not rows:
            print("No trainer_ratings rows found.", file=sys.stderr)
            return 1

        exit_code = 0
        for row in rows:
            result = await notify_trainer_for_stored_rating(session, row, dry_run=dry_run)
            print(json.dumps(result, ensure_ascii=False, default=str))
            if result.get("error"):
                exit_code = 2
        return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill trainer Telegram rating notifications")
    parser.add_argument("--rating-id", type=int, default=None, help="Single trainer_ratings.id (default: all rows)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve booking and print summary without sending Telegram",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.rating_id, args.dry_run)))
