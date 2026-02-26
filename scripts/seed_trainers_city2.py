"""
Seed 20 trainers for city_id=2: 10 linked to service_id=1, 10 to service_id=2.
Profile data (names, age, experience, description) is arbitrary for load testing.
Run from repo root: python scripts/seed_trainers_city2.py

Requires: cities and services already seeded (city id=2, services id=1 and 2 exist).
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

CITY_ID = 2
SERVICE_1_COUNT = 10
SERVICE_2_COUNT = 10
TOTAL = SERVICE_1_COUNT + SERVICE_2_COUNT
# One photo per seeded trainer (file_key in S3; same placeholder for all for dev/load testing)
DEFAULT_PHOTO_FILE_KEY = "trainers/3/6b9f6ad99cd7489caa980b8a6ca5fdd4.jpg"

FIRST_NAMES = [
    "Александр", "Дмитрий", "Артём", "Максим", "Иван", "Кирилл", "Никита", "Егор", "Андрей", "Илья",
    "Михаил", "Роман", "Владимир", "Сергей", "Павел", "Николай", "Олег", "Виктор", "Станислав", "Глеб",
]
LAST_NAMES = [
    "Иванов", "Козлов", "Новиков", "Морозов", "Петров", "Волков", "Соколов", "Лебедев", "Кузнецов", "Попов",
    "Васильев", "Смирнов", "Михайлов", "Федоров", "Романов", "Орлов", "Зайцев", "Соловьёв", "Борисов", "Яковлев",
]
DESCRIPTIONS = [
    "Индивидуальные и групповые занятия. Работа с детьми и взрослыми.",
    "Опыт выступления на соревнованиях. Постановка программ.",
    "Подход к каждому ученику. Развитие техники и выносливости.",
    "Работа над базой и сложными элементами. Подготовка к соревнованиям.",
    "Группы начального и продвинутого уровня. Детская и взрослая группы.",
]
EDUCATION = [
    "БГУФК, тренерский факультет.",
    "Институт физкультуры, специализация — игровые виды.",
    "Высшее физкультурное образование, КМС.",
]


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)

    with Session(engine) as session:
        # Ensure city 2 and services 1, 2 exist
        city = session.execute(text("SELECT id FROM cities WHERE id = :id"), {"id": CITY_ID}).fetchone()
        if not city:
            print("City id=2 not found. Run seed_cities.py first.")
            sys.exit(1)
        for sid in (1, 2):
            svc = session.execute(text("SELECT id FROM services WHERE id = :id"), {"id": sid}).fetchone()
            if not svc:
                print(f"Service id={sid} not found. Run seed_services.py first.")
                sys.exit(1)

        # Create 20 trainers with status=active; each gets profile + one service
        for i in range(TOTAL):
            r = session.execute(
                text("""
                    INSERT INTO trainers (status, created_at)
                    VALUES ('active'::trainer_status_enum, now())
                    RETURNING id
                """),
            )
            (tid,) = r.fetchone()

            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            age = random.randint(25, 55)
            exp = random.randint(2, min(25, age - 18)) if age > 20 else random.randint(1, 5)
            phone = f"+37529{random.randint(1000000, 9999999)}"
            desc = random.choice(DESCRIPTIONS)
            edu = random.choice(EDUCATION)

            session.execute(
                text("""
                    INSERT INTO trainer_profiles
                    (trainer_id, first_name, last_name, age, city_id, experience_years, description, phone, education)
                    VALUES (:tid, :fn, :ln, :age, :city_id, :exp, :desc, :phone, :edu)
                    ON CONFLICT (trainer_id) DO UPDATE SET
                    first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name, age = EXCLUDED.age,
                    city_id = EXCLUDED.city_id, experience_years = EXCLUDED.experience_years,
                    description = EXCLUDED.description, phone = EXCLUDED.phone, education = EXCLUDED.education,
                    updated_at = now()
                """),
                {
                    "tid": tid,
                    "fn": first,
                    "ln": last,
                    "age": age,
                    "city_id": CITY_ID,
                    "exp": exp,
                    "desc": desc,
                    "phone": phone,
                    "edu": edu,
                },
            )
            service_id = 1 if i < SERVICE_1_COUNT else 2
            session.execute(
                text("INSERT INTO trainer_services (trainer_id, service_id) VALUES (:tid, :sid) ON CONFLICT DO NOTHING"),
                {"tid": tid, "sid": service_id},
            )
            session.execute(
                text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:tid, :key, 0)"),
                {"tid": tid, "key": DEFAULT_PHOTO_FILE_KEY},
            )

        session.commit()

    print(f"Seeded {TOTAL} trainers for city_id={CITY_ID}: {SERVICE_1_COUNT} with service_id=1, {SERVICE_2_COUNT} with service_id=2.")


if __name__ == "__main__":
    main()
