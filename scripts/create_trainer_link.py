"""
Create a trainer and a one-time link token; print t.me link for trainer bot.
Usage: python scripts/create_trainer_link.py [--expire-days 7] [--bot-username YourBot]
For site: call this (or equivalent API) after registration/payment; give user the link.
"""
import argparse
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running as python scripts/create_trainer_link.py from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create trainer + link token")
    parser.add_argument("--expire-days", type=int, default=7, help="Token validity in days")
    parser.add_argument("--bot-username", type=str, default="", help="Trainer bot @username (for link)")
    args = parser.parse_args()
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=args.expire_days)
    with Session(engine) as session:
        r = session.execute(text("INSERT INTO trainers (created_at) VALUES (now()) RETURNING id"))
        (trainer_id,) = r.fetchone()
        session.execute(
            text(
                "INSERT INTO trainer_link_tokens (token, trainer_id, expires_at) VALUES (:t, :tid, :exp)"
            ),
            {"t": token, "tid": trainer_id, "exp": expires_at},
        )
        session.commit()
    # full deep link for Telegram
    link = f"https://t.me/{args.bot_username.lstrip('@')}?start=link_{token}" if args.bot_username else f"start=link_{token}"
    print(f"Trainer id: {trainer_id}")
    print(f"Token (use in link): link_{token}")
    print(f"Link: {link}")
    if not args.bot_username:
        print("Set --bot-username YourTrainerBot to get full t.me link", file=sys.stderr)


if __name__ == "__main__":
    main()
