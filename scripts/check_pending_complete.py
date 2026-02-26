"""
Read-only check: which bookings would be completed on next worker tick.

Run from project root:
  python -m scripts.check_pending_complete

Uses .env (via Settings) for DATABASE_URL.
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.booking_use_cases import list_bookings_to_complete
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings


async def main() -> None:
    try:
        Settings().database_url
    except Exception as e:
        print(f"Config error (check .env): {e}")
        sys.exit(1)
    async with async_session_factory() as session:
        to_complete = await list_bookings_to_complete(session)
    print(f"[{datetime.now().isoformat()}] list_bookings_to_complete: {len(to_complete)} booking(s)")
    for b in to_complete:
        print(f"  booking_id={b['id']} client_telegram_id={b['client_telegram_id']} trainer_id={b['trainer_id']} "
              f"slot_date={b['slot_date']} start={b['start_time']} end={b['end_time']}")
    if not to_complete:
        print("  (none — no pending bookings with slot end in the past)")


if __name__ == "__main__":
    asyncio.run(main())
