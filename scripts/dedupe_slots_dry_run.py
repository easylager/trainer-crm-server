#!/usr/bin/env python3
"""
Find identical duplicate slots (same trainer, date, window, venue; not cancelled) and show which free
twins would be dropped. DRY RUN by default: connection is read-only, nothing is written.

    DBURL=postgresql://... python3 scripts/dedupe_slots_dry_run.py [--from-date YYYY-MM-DD]

Rules (same as migration 0302_slot_dedupe):
  * keep the twin that has a booking (any status), else the one with status 'booked', else the lowest id;
  * drop only twins with status 'available' and no bookings at all — a booked slot is never dropped;
  * a group where several twins carry bookings is reported as MANUAL and left alone.

--apply prints the DELETE statement run in one transaction (needs DBURL with write rights). Not run by CI.
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg

SELECT_SQL = """
SELECT s.id, s.trainer_id, s.slot_date, s.start_time, s.end_time, s.arena_id, s.status,
       (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id) AS n_bookings,
       ROW_NUMBER() OVER (
           PARTITION BY s.trainer_id, s.slot_date, s.start_time, s.end_time, COALESCE(s.arena_id, 0)
           ORDER BY (EXISTS (SELECT 1 FROM bookings b WHERE b.slot_id = s.id)) DESC,
                    (s.status = 'booked') DESC, s.id
       ) AS rn,
       COUNT(*) OVER (
           PARTITION BY s.trainer_id, s.slot_date, s.start_time, s.end_time, COALESCE(s.arena_id, 0)
       ) AS grp_size
FROM slots s
WHERE s.status <> 'cancelled' AND s.slot_date >= %(from_date)s
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", default="1970-01-01")
    ap.add_argument("--apply", action="store_true", help="really delete the free twins (default: dry run)")
    args = ap.parse_args()
    url = os.environ.get("DBURL")
    if not url:
        print("set DBURL", file=sys.stderr)
        return 2
    with psycopg.connect(url) as conn:
        conn.read_only = not args.apply
        rows = conn.execute(SELECT_SQL, {"from_date": args.from_date}).fetchall()
        dup = [r for r in rows if r[9] > 1]
        groups: dict[tuple, list[tuple]] = {}
        for r in dup:
            groups.setdefault((r[1], r[2], r[3], r[4], r[5]), []).append(r)
        drop: list[int] = []
        manual = 0
        for key, members in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2])):
            booked_members = [m for m in members if m[7] > 0]
            if len(booked_members) > 1:
                manual += 1
                print(f"MANUAL  trainer={key[0]} {key[1]} {key[2]}-{key[3]} arena={key[4]} ids={[m[0] for m in members]}")
            for m in members:
                if m[8] > 1 and m[6] == "available" and m[7] == 0:
                    drop.append(m[0])
                    print(f"DROP    slot {m[0]} (trainer={m[1]} {m[2]} {m[3]}-{m[4]}) keep={[x[0] for x in members if x[8] == 1][0]}")
        print(
            f"\nduplicate groups: {len(groups)}, trainers: {len({k[0] for k in groups})}, "
            f"groups with a booked twin: {sum(1 for g in groups.values() if any(m[7] for m in g))}, "
            f"free twins to drop: {len(drop)}, manual groups: {manual}"
        )
        if args.apply and drop:
            n = conn.execute(
                "DELETE FROM slots WHERE id = ANY(%s) AND status = 'available' "
                "AND NOT EXISTS (SELECT 1 FROM bookings b WHERE b.slot_id = slots.id)",
                (drop,),
            ).rowcount
            conn.commit()
            print(f"deleted {n}")
        elif not args.apply:
            print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
