"""Test trainers with bookable slots at regional ice arenas (local dev DB only).

Purpose: let a human click through "arena card -> book a trainer" for real, with
slots placed both *during* a live ice_sessions MK window (coaching alongside open
skate) and *outside* it (private ice before/after MK hours) — the two cases that
matter for TASK-056 "place = slot's arena, not trainer's primary arena".

Each trainer gets an active subscription with the online-booking module enabled
(tier='online', modules.online=true) — without this, get_trainer_booking_availability
returns can_book=False and the arena card shows no booking CTA at all.

Default is dry-run. ``--apply`` writes to a local test/dev DB only — never production.

Usage:
  PYTHONPATH=. python scripts/seed_test_trainers_regional_arenas.py
  PYTHONPATH=. python scripts/seed_test_trainers_regional_arenas.py --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "db", "host.docker.internal"})
CLOUD_DB_MARKERS = (
    "railway", "supabase", "neon.tech", "amazonaws.com", "azure", "render.com",
    "onrender.com", "planetscale", "digitalocean", "prod.", "production",
)
ALLOWED_APPLY_DB_NAMES = frozenset({"trainer_crm_test", "trainer_crm"})


class ProdDatabaseError(RuntimeError):
    pass


def _assert_local_database(url: str, *, apply: bool) -> None:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    host = (parsed.hostname or "").lower()
    haystack = f"{host} {url.lower()}"
    if any(marker in haystack for marker in CLOUD_DB_MARKERS):
        raise ProdDatabaseError(f"refusing cloud/prod database host {host!r}")
    local_ok = host in LOCAL_DB_HOSTS or (host.startswith("127.") and host.count(".") == 3)
    if not local_ok:
        raise ProdDatabaseError(f"refusing non-local database host {host!r}")
    if not apply:
        return
    dbname = (parsed.path or "").lstrip("/").split("?")[0]
    if dbname not in ALLOWED_APPLY_DB_NAMES:
        raise ProdDatabaseError(f"apply is limited to {sorted(ALLOWED_APPLY_DB_NAMES)}, got {dbname!r}")


TOMORROW = date(2026, 9, 8)  # matches the live ice_sessions already ingested for 2026-09-07/08

TRAINERS = [
    {
        "arena_id": 10,  # ТЦ «Тринити», Гродно — MK runs 11:00-20:45 hourly, 45-min sessions
        "city_id": 60,
        "first_name": "Артём",
        "last_name": "Ковальчук",
        "experience_years": 7,
        "description": "Индивидуальные занятия для начинающих на льду ТЦ «Тринити». Ставлю базовую технику катания взрослым и детям от 5 лет.",
        "phone": "+375291990001",
        "education": "ГрГУ им. Янки Купалы, факультет физического воспитания.",
        "service_id": 1,  # Обучение катанию «с нуля»
        "price_cents": 4000,
        "slots": [
            # During МК (14:00-14:45 session) — coaching alongside open skate.
            {"date": TOMORROW, "start": time(14, 0), "end": time(14, 45), "note": "during MK"},
            # Outside МК hours (rink opens for MK at 11:00) — private ice.
            {"date": TOMORROW, "start": time(9, 0), "end": time(9, 45), "note": "before MK"},
        ],
    },
    {
        "arena_id": 10,
        "city_id": 60,
        "first_name": "Виктория",
        "last_name": "Дуброўская",
        "experience_years": 5,
        "description": "Фигурное катание для детей 4-12 лет. Группы и индивидуально, работаю на «Тринити».",
        "phone": "+375291990002",
        "education": "БГУФК, специализация фигурное катание. КМС.",
        "service_id": 3,  # Фигурное катание
        "price_cents": 4500,
        "slots": [
            {"date": TOMORROW, "start": time(17, 0), "end": time(17, 45), "note": "during MK"},
            {"date": TOMORROW, "start": time(21, 0), "end": time(21, 45), "note": "after MK closes"},
        ],
    },
    {
        "arena_id": 22,  # Брестский ЛДС — MK 21:15-22:15 daily
        "city_id": 57,
        "first_name": "Дмитрий",
        "last_name": "Шевчук",
        "experience_years": 9,
        "description": "Хоккейное катание, работа с клюшкой и шайбой. Индивидуально и малыми группами, Брестский ЛДС.",
        "phone": "+375291990003",
        "education": "БрГУ им. А.С. Пушкина, тренерский факультет.",
        "service_id": 4,  # Хоккейное катание
        "price_cents": 5000,
        "slots": [
            # During МК (21:15-22:15) — overlaps the evening session end.
            {"date": TOMORROW, "start": time(21, 15), "end": time(22, 0), "note": "during MK"},
            # Well before МК — private ice.
            {"date": TOMORROW, "start": time(18, 0), "end": time(18, 45), "note": "before MK"},
        ],
    },
]


def _database_url() -> str:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _print_plan() -> None:
    print(f"Trainers to seed: {len(TRAINERS)}")
    for t in TRAINERS:
        print(f"  {t['first_name']} {t['last_name']} — arena_id={t['arena_id']} service_id={t['service_id']}")
        for s in t["slots"]:
            print(f"    slot {s['date']} {s['start']}-{s['end']} ({s['note']})")


def run(*, apply: bool) -> None:
    url = _database_url()
    _assert_local_database(url, apply=apply)
    if not apply:
        _print_plan()
        print("\nDry-run only. Re-run with --apply to write to the local DB.")
        return

    engine = create_engine(url)
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=365)
        for t in TRAINERS:
            for ref, table in ((t["arena_id"], "arenas"), (t["city_id"], "cities"), (t["service_id"], "services")):
                found = session.execute(text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": ref}).scalar()
                if not found:
                    print(f"{table} id={ref} not found — skipping {t['first_name']} {t['last_name']}")
                    break
            else:
                tid = session.execute(
                    text(
                        "INSERT INTO trainers (status, is_catalog_visible, created_at) "
                        "VALUES ('active'::trainer_status_enum, true, now()) RETURNING id"
                    )
                ).scalar_one()

                session.execute(
                    text(
                        "INSERT INTO trainer_profiles "
                        "(trainer_id, first_name, last_name, city_id, experience_years, description, "
                        " phone, education, session_duration_minutes, min_hours_before_booking) "
                        "VALUES (:tid, :fn, :ln, :city_id, :exp, :desc, :phone, :edu, 45, 1)"
                    ),
                    {
                        "tid": tid,
                        "fn": t["first_name"],
                        "ln": t["last_name"],
                        "city_id": t["city_id"],
                        "exp": t["experience_years"],
                        "desc": t["description"],
                        "phone": t["phone"],
                        "edu": t["education"],
                    },
                )

                session.execute(
                    text(
                        "INSERT INTO trainer_services (trainer_id, service_id, price_cents) "
                        "VALUES (:tid, :sid, :price) "
                        "ON CONFLICT (trainer_id, service_id) DO UPDATE SET price_cents = EXCLUDED.price_cents"
                    ),
                    {"tid": tid, "sid": t["service_id"], "price": t["price_cents"]},
                )

                session.execute(
                    text(
                        "INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) "
                        "VALUES (:tid, :aid, true) ON CONFLICT (trainer_id, arena_id) DO NOTHING"
                    ),
                    {"tid": tid, "aid": t["arena_id"]},
                )

                session.execute(
                    text(
                        "INSERT INTO trainer_subscriptions "
                        "(trainer_id, plan_id, started_at, expires_at, status, tier, modules) "
                        "VALUES (:tid, "
                        " (SELECT id FROM subscription_plans WHERE is_trial = true LIMIT 1), "
                        " :started_at, :expires_at, 'active', 'online'::subscription_tier_enum, "
                        " '{\"online\": true, \"analytics\": false, \"groups\": false}'::jsonb)"
                    ),
                    {"tid": tid, "started_at": now, "expires_at": expires_at},
                )

                for s in t["slots"]:
                    session.execute(
                        text(
                            "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, "
                            "arena_id, service_id) "
                            "VALUES (:tid, :d, :st, :et, 'available', :aid, :sid)"
                        ),
                        {
                            "tid": tid,
                            "d": s["date"],
                            "st": s["start"],
                            "et": s["end"],
                            "aid": t["arena_id"],
                            "sid": t["service_id"],
                        },
                    )

                print(f"seeded trainer_id={tid} {t['first_name']} {t['last_name']} arena_id={t['arena_id']}")

        session.commit()
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run(apply=args.apply)


if __name__ == "__main__":
    main()
