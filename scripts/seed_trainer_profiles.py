"""
Fill a couple of trainer profiles (first_name, last_name, age, experience_years, etc.).
Run after migrations and seed_services. Usage: python scripts/seed_trainer_profiles.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

PROFILES = [
    {
        "first_name": "Арсен",
        "last_name": "Венгер",
        "age": 60,
        "experience_years": 30,
        "description": "Тренер по хоккею. КМС. Работа с детьми и взрослыми.",
        "phone": "+375291234567",
        "education": "БГУФК, тренер по хоккею.",
        "service_ids": [1, 4],  # Хоккей, ОФП
    },
    {
        "first_name": "Жозэ",
        "last_name": "Моуринье",
        "age": 55,
        "experience_years": 20,
        "description": "Фигурное катание, постановка программ.",
        "phone": "+375331234567",
        "education": "Институт физкультуры, фигурное катание.",
        "service_ids": [2, 4],  # Фигурное катание, ОФП
    },
]


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)
    with Session(engine) as session:
        ids = [r[0] for r in session.execute(text("SELECT id FROM trainers ORDER BY id LIMIT 2")).fetchall()]
        while len(ids) < 2:
            session.execute(text("INSERT INTO trainers (created_at) VALUES (now())"))
            (new_id,) = session.execute(text("SELECT id FROM trainers ORDER BY id DESC LIMIT 1")).fetchone()
            ids.append(new_id)
        for tid, p in zip(ids[:2], PROFILES):
            session.execute(
                text("""
                    INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, experience_years, description, phone, education)
                    VALUES (:tid, :fn, :ln, :age, :exp, :desc, :phone, :edu)
                    ON CONFLICT (trainer_id) DO UPDATE SET
                    first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name, age = EXCLUDED.age,
                    experience_years = EXCLUDED.experience_years, description = EXCLUDED.description,
                    phone = EXCLUDED.phone, education = EXCLUDED.education, updated_at = now()
                """),
                {
                    "tid": tid,
                    "fn": p["first_name"],
                    "ln": p["last_name"],
                    "age": p["age"],
                    "exp": p["experience_years"],
                    "desc": p["description"],
                    "phone": p["phone"],
                    "edu": p["education"],
                },
            )
            session.execute(text("DELETE FROM trainer_services WHERE trainer_id = :tid"), {"tid": tid})
            for sid in p["service_ids"]:
                session.execute(
                    text("INSERT INTO trainer_services (trainer_id, service_id) VALUES (:tid, :sid) ON CONFLICT DO NOTHING"),
                    {"tid": tid, "sid": sid},
                )
        session.commit()
    print("Trainer profiles seeded.")


if __name__ == "__main__":
    main()
