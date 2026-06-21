#!/usr/bin/env python3
"""Diagnose why trainer decline may fail for a booking (run against prod/staging DB)."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.booking_use_cases import decline_booking
from src.application.trainer_link import get_trainer_id_by_telegram_id
from src.shared.config import Settings


async def _run(args: argparse.Namespace) -> int:
    engine = create_async_engine(Settings().database_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    clauses = ["1=1"]
    params: dict = {}
    if args.booking_id:
        clauses.append("b.id = :booking_id")
        params["booking_id"] = int(args.booking_id)
    if args.date:
        clauses.append("s.slot_date = :slot_date")
        params["slot_date"] = args.date
    if args.time:
        clauses.append("s.start_time = :start_time")
        params["start_time"] = args.time if len(args.time) > 5 else f"{args.time}:00"
    if args.client:
        clauses.append(
            "(c.first_name ILIKE :client OR c.last_name ILIKE :client "
            "OR TRIM(COALESCE(c.first_name,'') || ' ' || COALESCE(c.last_name,'')) ILIKE :client)"
        )
        params["client"] = f"%{args.client.strip()}%"

    sql = f"""
        SELECT
            b.id AS booking_id,
            b.status AS booking_status,
            b.created_at,
            b.notified_at,
            b.trainer_id,
            t.telegram_id AS trainer_telegram_id,
            t.status AS trainer_account_status,
            s.id AS slot_id,
            s.status AS slot_status,
            s.slot_date,
            s.start_time,
            s.end_time,
            TRIM(COALESCE(c.first_name,'') || ' ' || COALESCE(c.last_name,'')) AS client_name,
            srv.name AS service_name
        FROM bookings b
        JOIN clients c ON c.id = b.client_id
        JOIN slots s ON s.id = b.slot_id
        JOIN services srv ON srv.id = b.service_id
        JOIN trainers t ON t.id = b.trainer_id
        WHERE {" AND ".join(clauses)}
        ORDER BY b.id DESC
        LIMIT 20
    """
    async with Session() as session:
        rows = (await session.execute(text(sql), params)).fetchall()
        if not rows:
            print("No bookings matched.")
            return 1
        for row in rows:
            m = dict(row._mapping)
            print("---")
            for k, v in m.items():
                print(f"{k}: {v}")
            booking_id = int(m["booking_id"])
            trainer_id = int(m["trainer_id"])
            trainer_tg = m.get("trainer_telegram_id")
            reasons: list[str] = []
            if (m.get("booking_status") or "") != "pending":
                reasons.append(f"booking.status={m.get('booking_status')} (decline only works for pending)")
            slot_st = (m.get("slot_status") or "").strip().lower()
            if slot_st == "cancelled":
                reasons.append("slot.status=cancelled (slot removed from schedule)")
            if trainer_tg:
                linked = await get_trainer_id_by_telegram_id(session, int(trainer_tg))
                if not linked:
                    reasons.append(
                        f"trainer telegram {trainer_tg} not linked as active "
                        f"(account status={m.get('trainer_account_status')})"
                    )
            else:
                reasons.append("trainer has no telegram_id")
            if reasons:
                print("likely_blockers:")
                for r in reasons:
                    print(f"  - {r}")
            else:
                print("decline_precheck: looks declineable")
            if args.try_decline:
                info = await decline_booking(session, booking_id, trainer_id)
                print("decline_booking(dry):", "OK" if info else "FAILED (returned None)")
                if info:
                    await session.rollback()
                    print("(rolled back — dry run only)")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--booking-id", type=int)
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--time", help="HH:MM")
    p.add_argument("--client", help="Client name substring, e.g. Алина")
    p.add_argument("--try-decline", action="store_true", help="Call decline_booking and rollback")
    args = p.parse_args()
    if not any([args.booking_id, args.date, args.client]):
        p.error("Pass --booking-id and/or --date/--client filters")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
