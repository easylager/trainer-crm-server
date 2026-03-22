"""
Add 2 trainers: city_id=2, service_id=1, arena_id=3.
Full profile data, one photo each, active subscription (trial), so they appear in the catalog.
Run from repo root: python scripts/seed_two_trainers_city2_service1_arena3.py

Requires: city 2, service 1, arena 3 and subscription_plans (trial) exist.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

CITY_ID = 2
SERVICE_ID = 1
ARENA_ID = 3
DEFAULT_PHOTO_FILE_KEY = "trainers/3/6b9f6ad99cd7489caa980b8a6ca5fdd4.jpg"

TRAINERS = [
    {
        "first_name": "Станислав",
        "last_name": "Ковалёв",
        "age": 38,
        "experience_years": 12,
        "description": "Тренер по хоккею. Работа с детьми от 5 лет и взрослыми. Индивидуальные и групповые занятия. Подготовка к соревнованиям, постановка техники катания и владения клюшкой.",
        "phone": "+375291234501",
        "contacts": "Telegram: @kovalev_trainer",
        "education": "БГУФК, тренерский факультет. КМС по хоккею.",
        "session_duration_minutes": 60,
        "min_hours_before_booking": 3,
        "rating_avg": 4.8,
        "rating_count": 24,
        "price_cents": 5500,  # 55 BYN за занятие
    },
    {
        "first_name": "Ольга",
        "last_name": "Семёнова",
        "age": 34,
        "experience_years": 9,
        "description": "Хоккей и ОФП для детей и взрослых. Группы начального и продвинутого уровня. Упор на технику и безопасность. Работаю на арене 3.",
        "phone": "+375331234502",
        "contacts": "Telegram: @semenova_arena3",
        "education": "Институт физкультуры, специализация — игровые виды. Мастер спорта.",
        "session_duration_minutes": 45,
        "min_hours_before_booking": 3,
        "rating_avg": 4.9,
        "rating_count": 31,
        "price_cents": 5000,  # 50 BYN за занятие
    },
]


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)

    with Session(engine) as session:
        for ref in (CITY_ID, SERVICE_ID, ARENA_ID):
            table = "cities" if ref == CITY_ID else ("services" if ref == SERVICE_ID else "arenas")
            col = "id"
            row = session.execute(text(f"SELECT {col} FROM {table} WHERE id = :id"), {"id": ref}).fetchone()
            if not row:
                print(f"{table} id={ref} not found. Seed cities, services, arenas first.")
                sys.exit(1)

        trial = session.execute(
            text("SELECT id FROM subscription_plans WHERE is_trial = true LIMIT 1")
        ).fetchone()
        if not trial:
            print("No trial subscription_plans. Run migrations (0042, 0045) first.")
            sys.exit(1)
        plan_id = trial[0]

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=365)

        for p in TRAINERS:
            r = session.execute(
                text("""
                    INSERT INTO trainers (status, created_at)
                    VALUES ('active'::trainer_status_enum, now())
                    RETURNING id
                """),
            )
            (tid,) = r.fetchone()

            session.execute(
                text("""
                    INSERT INTO trainer_profiles
                    (trainer_id, first_name, last_name, age, city_id, experience_years, description,
                     phone, contacts, education, session_duration_minutes, min_hours_before_booking,
                     rating_avg, rating_count)
                    VALUES (:tid, :fn, :ln, :age, :city_id, :exp, :desc, :phone, :contacts, :edu,
                            :dur, :mh, :rating_avg, :rating_count)
                """),
                {
                    "tid": tid,
                    "fn": p["first_name"],
                    "ln": p["last_name"],
                    "age": p["age"],
                    "city_id": CITY_ID,
                    "exp": p["experience_years"],
                    "desc": p["description"],
                    "phone": p["phone"],
                    "contacts": p.get("contacts"),
                    "edu": p["education"],
                    "dur": p["session_duration_minutes"],
                    "mh": p.get("min_hours_before_booking", 3),
                    "rating_avg": p.get("rating_avg"),
                    "rating_count": p.get("rating_count", 0),
                },
            )

            session.execute(
                text("""
                    INSERT INTO trainer_services (trainer_id, service_id, price_cents)
                    VALUES (:tid, :sid, :price_cents)
                    ON CONFLICT (trainer_id, service_id) DO UPDATE SET price_cents = EXCLUDED.price_cents
                """),
                {"tid": tid, "sid": SERVICE_ID, "price_cents": p["price_cents"]},
            )

            session.execute(
                text("""
                    INSERT INTO trainer_arenas (trainer_id, arena_id)
                    VALUES (:tid, :aid)
                    ON CONFLICT (trainer_id, arena_id) DO NOTHING
                """),
                {"tid": tid, "aid": ARENA_ID},
            )

            session.execute(
                text("""
                    INSERT INTO trainer_photos (trainer_id, file_key, sort_order)
                    VALUES (:tid, :key, 0)
                """),
                {"tid": tid, "key": DEFAULT_PHOTO_FILE_KEY},
            )

            session.execute(
                text("""
                    INSERT INTO trainer_subscriptions (trainer_id, plan_id, started_at, expires_at, status)
                    VALUES (:tid, :plan_id, :started_at, :expires_at, 'active')
                """),
                {
                    "tid": tid,
                    "plan_id": plan_id,
                    "started_at": now,
                    "expires_at": expires_at,
                },
            )

        session.commit()

    print(
        f"Seeded 2 trainers: city_id={CITY_ID}, service_id={SERVICE_ID}, arena_id={ARENA_ID}. "
        "Profiles, services, arenas, one photo each, active subscription."
    )


if __name__ == "__main__":
    main()
