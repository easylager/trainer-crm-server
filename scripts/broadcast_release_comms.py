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

  # Игра «Кто кого»: segment: by_clients в файле. Журнал — в БД (client_broadcast_log, campaign_key = release_id),
  # повторный запуск не дублирует. Волны: сначала 10% аудитории, потом больше.
  python -m scripts.broadcast_release_comms --message docs/release-comms/<файл>.clients.md --dry-run
  python -m scripts.broadcast_release_comms --message docs/release-comms/<файл>.clients.md --percent 10
  python -m scripts.broadcast_release_comms --message docs/release-comms/<файл>.clients.md --percent 50 --limit 500

  # Только часть городов и без тех, кому уже ушла другая кампания (поля шапки, только для by_clients):
  #   ---
  #   release_id: 2026-11-12-kto-kogo-regions
  #   audience: clients
  #   segment: by_clients
  #   cities: Орша, Могилёв, Барановичи
  #   exclude_campaigns: 2026-11-11-kto-kogo-orsha
  #   ---
  # Города — названия из cities (BY), регистр и ё/е не важны; неизвестное название — ошибка до отправки.
  # Город человека — из сессии, а без него — город арены его записи. exclude_campaigns — release_id,
  # чьи получатели (любой status в client_broadcast_log) выпадают из аудитории. --dry-run печатает
  # "filters": сколько было, сколько по каждому городу, сколько исключено кампаниями, сколько осталось.

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

from src.application.ice_forecast import describe_markup
from src.application.release_comms_use_cases import (
    broadcast_release_comms,
    build_webapp_markup,
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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Send to at most N recipients (by_clients: N new sends per run, journal already skipped)",
    )
    parser.add_argument(
        "--percent",
        type=float,
        default=None,
        help="Only for segment by_clients: wave = first P%% of the audience in a stable order; "
        "run again with a larger P to send the rest of that wave",
    )
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
            percent=args.percent,
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
    if result.sample_ids is not None:
        summary["would_send"] = result.would_send
        summary["sample_telegram_ids"] = result.sample_ids
    if result.filters is not None:
        summary["filters"] = result.filters
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.dry_run and result.sample_ids is not None:
        # Что именно уйдёт: текст и кнопки так, как их увидит человек.
        markup = build_webapp_markup(settings, spec)
        print("--- text ---")
        print(spec.html_body)
        print("--- buttons ---")
        for line in describe_markup(markup):
            print(line)

    if result.failed and not args.dry_run:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
