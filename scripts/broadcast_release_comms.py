"""
Broadcast release comms from docs/release-comms/*.md to clients or trainers.

Usage:
  # Preview to yourself
  python -m scripts.broadcast_release_comms \\
    --message docs/release-comms/2026-08-26-glide-rebrand.clients.md \\
    --chat-id YOUR_TELEGRAM_ID

  # Dry-run (count audience, no send)
  python -m scripts.broadcast_release_comms \\
    --message docs/release-comms/2026-08-26-glide-rebrand.clients.md \\
    --dry-run

  # Send to all clients (skips already sent for this release_id unless --force)
  python -m scripts.broadcast_release_comms \\
    --message docs/release-comms/2026-08-26-glide-rebrand.clients.md

  python -m scripts.broadcast_release_comms \\
    --message docs/release-comms/2026-08-26-glide-rebrand.trainers.md

Env: .env with database_url, TELEGRAM_BOT_TOKEN_CLIENT, TELEGRAM_BOT_TOKEN_TRAINER,
     WEBAPP_BASE_URL (https — for WebApp button on message).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.release_comms_use_cases import (
    broadcast_release_comms,
    parse_release_comms_file,
)
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Broadcast release comms to clients or trainers")
    parser.add_argument(
        "--message",
        type=Path,
        required=True,
        help="Path to .md file with YAML frontmatter (see docs/release-comms/TEMPLATE.md)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count recipients only")
    parser.add_argument(
        "--chat-id",
        type=int,
        default=None,
        help="Send to one Telegram user (preview); does not update delivery log",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore delivery log and resend to everyone in audience",
    )
    parser.add_argument("--limit", type=int, default=None, help="Send to at most N recipients")
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=50,
        help="Pause between sends in ms (default 50)",
    )
    args = parser.parse_args()

    path = args.message if args.message.is_absolute() else ROOT / args.message
    if not path.is_file():
        logger.error("Message file not found: %s", path)
        return 1

    spec = parse_release_comms_file(path)
    settings = Settings()

    if args.chat_id is None and not args.dry_run:
        logger.info(
            "release_id=%s audience=%s — sending to full audience",
            spec.release_id,
            spec.audience,
        )
    elif args.chat_id is not None:
        logger.info("Preview mode → chat_id=%s", args.chat_id)

    async with async_session_factory() as session:
        result = await broadcast_release_comms(
            session,
            spec,
            settings=settings,
            dry_run=args.dry_run,
            chat_id=args.chat_id,
            force=args.force,
            limit=args.limit,
            send_delay_sec=max(0, args.delay_ms) / 1000.0,
        )

    summary = {
        "release_id": result.release_id,
        "audience": result.audience,
        "dry_run": result.dry_run,
        "total": result.total,
        "sent": result.sent,
        "skipped": result.skipped,
        "failed": result.failed,
        "errors_sample": result.errors[:5],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if result.failed and not args.dry_run:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
