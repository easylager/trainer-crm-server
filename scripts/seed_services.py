"""
Insert default services into the catalog. Run once after migration 0003.
Usage: python scripts/seed_services.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

DEFAULTS = [
    ("Хоккей", 10),
    ("Фигурное катание", 20),
    ("Конькобежный спорт", 30),
    ("Общая физическая подготовка", 40),
]


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)
    with Session(engine) as session:
        (n,) = session.execute(text("SELECT COUNT(*) FROM services")).fetchone()
        if n > 0:
            print("Services already present, skip.")
            return
        for name, sort_order in DEFAULTS:
            session.execute(
                text("INSERT INTO services (name, sort_order) VALUES (:name, :ord)"),
                {"name": name, "ord": sort_order},
            )
        session.commit()
    print("Services seeded.")


if __name__ == "__main__":
    main()
