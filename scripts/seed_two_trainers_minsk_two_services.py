"""
Добавить 2 «тестовых» тренера в Минске на *разные услуги* (каталог / сохранения / edges).

Ищет город по имени «Минск», арену — первую в этом городе; услуги — по точным именам из 0028_seed_services.

Запуск из корня репозитория::

    venv/bin/python scripts/seed_two_trainers_minsk_two_services.py

Нужны: cities, services, arenas (см. scripts/seed_cities.py, seed_services.py, seed_arenas.py),
план подписки с is_trial или любой trial-план.

Фото: по умолчанию тот же file_key, что и в других сидах (должен существовать в S3/local_storage,
если хотите свои снимки — залейте через мини-приложение тренера после линка Telegram, см. докстринг ниже).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

# Две разные услуги из стандартного сида (не пересекаются — удобно проверять фильтр / избранное).
SERVICE_NAME_A = "Обучение катанию «с нуля»"
SERVICE_NAME_B = "ОФП/СФП"

CITY_NAME = "Минск"

# Плейсхолдер как в seed_two_trainers_city2_service1_arena3.py (локально — положите файл по пути local_storage).
DEFAULT_PHOTO_FILE_KEY = "trainers/3/6b9f6ad99cd7489caa980b8a6ca5fdd4.jpg"

TRAINERS: list[dict] = [
    {
        "service_name": SERVICE_NAME_A,
        "first_name": "Демо",
        "last_name": "КатаниеСНуля",
        "birth_date": "1994-03-15",
        "experience_years": 8,
        "description": "Тестовый тренер услуги «с нуля»: индивидуально и в мини-группах. Для проверки каталога и «Сохранить».",
        "phone": "+375291111001",
        "contacts": "Telegram: @demo_trainer_a",
        "education": "БГУФК.",
        "session_duration_minutes": 60,
        "min_hours_before_booking": 3,
        "rating_avg": 4.7,
        "rating_count": 5,
        "price_cents": 6000,
    },
    {
        "service_name": SERVICE_NAME_B,
        "first_name": "Тест",
        "last_name": "ОФП",
        "birth_date": "1997-08-20",
        "experience_years": 6,
        "description": "Тестовый тренер ОФП — вторая услуга, чтобы сравнить карточки и избранное в одном городе.",
        "phone": "+375292222002",
        "contacts": "Telegram: @demo_trainer_b",
        "education": "Институт физкультуры.",
        "session_duration_minutes": 45,
        "min_hours_before_booking": 3,
        "rating_avg": 4.8,
        "rating_count": 4,
        "price_cents": 4500,
    },
]


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)

    with Session(engine) as session:
        cid = session.execute(
            text("SELECT id FROM cities WHERE name = :n LIMIT 1"),
            {"n": CITY_NAME},
        ).scalar()
        if cid is None:
            print(f'Город «{CITY_NAME}» не найден. Запустите: venv/bin/python scripts/seed_cities.py')
            sys.exit(1)

        arena_row = session.execute(
            text("SELECT id FROM arenas WHERE city_id = :cid AND is_active = true ORDER BY sort_order, id LIMIT 1"),
            {"cid": cid},
        ).fetchone()
        if not arena_row:
            print(f"Нет арены в городе id={cid}. Запустите: venv/bin/python scripts/seed_arenas.py")
            sys.exit(1)
        arena_id = int(arena_row[0])

        service_ids: dict[str, int] = {}
        for name in (SERVICE_NAME_A, SERVICE_NAME_B):
            sid = session.execute(
                text("SELECT id FROM services WHERE name = :n LIMIT 1"),
                {"n": name},
            ).scalar()
            if sid is None:
                print(f'Услуга «{name}» не найдена. Запустите миграции / scripts/seed_services.py')
                sys.exit(1)
            service_ids[name] = int(sid)

        trial = session.execute(text("SELECT id FROM subscription_plans WHERE is_trial = true LIMIT 1")).fetchone()
        if not trial:
            trial = session.execute(
                text("SELECT id FROM subscription_plans ORDER BY id LIMIT 1")
            ).fetchone()
        if not trial:
            print("Нет subscription_plans — проверьте миграции.")
            sys.exit(1)
        plan_id = trial[0]

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=365)
        created_ids: list[int] = []

        for p in TRAINERS:
            sname = p["service_name"]
            srv_id = service_ids[sname]

            r = session.execute(
                text("""
                    INSERT INTO trainers (status, created_at)
                    VALUES ('active'::trainer_status_enum, now())
                    RETURNING id
                """),
            )
            (tid,) = r.fetchone()
            tid = int(tid)
            created_ids.append(tid)

            session.execute(
                text("""
                    INSERT INTO trainer_profiles
                    (trainer_id, first_name, last_name, birth_date, city_id, experience_years, description,
                     phone, contacts, education, session_duration_minutes, min_hours_before_booking,
                     rating_avg, rating_count)
                    VALUES (:tid, :fn, :ln, :birth_date, :city_id, :exp, :desc, :phone, :contacts, :edu,
                            :dur, :mh, :rating_avg, :rating_count)
                """),
                {
                    "tid": tid,
                    "fn": p["first_name"],
                    "ln": p["last_name"],
                    "birth_date": p["birth_date"],
                    "city_id": cid,
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
                {"tid": tid, "sid": srv_id, "price_cents": p["price_cents"]},
            )

            session.execute(
                text("""
                    INSERT INTO trainer_arenas (trainer_id, arena_id)
                    VALUES (:tid, :aid)
                    ON CONFLICT (trainer_id, arena_id) DO NOTHING
                """),
                {"tid": tid, "aid": arena_id},
            )

            session.execute(
                text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
                {"tid": tid, "aid": arena_id},
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

    print(f"Готово. Минск city_id={cid}, арена arena_id={arena_id}")
    print(f"Услуги: «{SERVICE_NAME_A}» id={service_ids[SERVICE_NAME_A]}, «{SERVICE_NAME_B}» id={service_ids[SERVICE_NAME_B]}")
    print(f"Добавлены trainer_id: {created_ids}")
    print()
    print("Фото профиля потом:")
    print("  • Мини-приложение тренера → профиль → загрузка (multipart POST /api/webapp/trainer/photos")
    print("    с заголовком X-Telegram-Init-Data) или пресайн PUT: POST …/trainer/photos/presign.")
    print("  • Сервер режет большие jpeg, сохраняет ключи в S3 или LOCAL_STORAGE.")
    print("  • Свой file_key можно подставить в trainer_photos вручную только если объект уже есть в бакете/папке.")


if __name__ == "__main__":
    main()
