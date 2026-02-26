"""
Seed cities for client bot city picker. Run from repo root: PYTHONPATH=. python scripts/seed_cities.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

CITIES = [
    ("Минск", 0),
    ("Гомель", 1),
    ("Могилёв", 2),
    ("Витебск", 3),
    ("Гродно", 4),
    ("Брест", 5),
]


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)
    with Session(engine) as session:
        for name, sort_order in CITIES:
            session.execute(
                text("""
                    INSERT INTO cities (name, sort_order)
                    SELECT :name, :ord
                    WHERE NOT EXISTS (SELECT 1 FROM cities WHERE name = :name)
                """),
                {"name": name, "ord": sort_order},
            )
        session.commit()
    print("Cities seeded.")


if __name__ == "__main__":
    main()
