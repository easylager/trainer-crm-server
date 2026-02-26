"""
Add one photo to trainers with id from 9 to 28 (same file_key for all).
Run from repo root: python scripts/seed_trainer_photos_9_28.py

Useful after seed_trainers_city2.py when trainers 9–28 already exist without photos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

TRAINER_ID_MIN = 9
TRAINER_ID_MAX = 28
FILE_KEY = "trainers/3/6b9f6ad99cd7489caa980b8a6ca5fdd4.jpg"


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)

    with Session(engine) as session:
        for tid in range(TRAINER_ID_MIN, TRAINER_ID_MAX + 1):
            session.execute(
                text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:tid, :key, 0)"),
                {"tid": tid, "key": FILE_KEY},
            )
        session.commit()

    print(f"Added photo {FILE_KEY} to trainers {TRAINER_ID_MIN}–{TRAINER_ID_MAX}.")


if __name__ == "__main__":
    main()
