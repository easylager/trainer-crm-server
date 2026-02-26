"""
Seed arenas per city for client filter and trainer slots. Run after seed_cities.
For Minsk: real addresses + coordinates (Yandex.by). Other cities: placeholder address.
PYTHONPATH=. python scripts/seed_arenas.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings

# Real venues in Minsk for demo (address + lat, lon for Yandex.by)
MINSK_ARENAS = [
    ("Арена 1 (Минск)", "Минск, пр. Рокоссовского, 114", 53.8647, 27.5892),   # Чижовка-Арена area
    ("Арена 2 (Минск)", "Минск, пр. Победителей, 111", 53.9311, 27.4828),     # Минск-Арена area
]


def main() -> None:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    engine = create_engine(url)
    with Session(engine) as session:
        r = session.execute(text("SELECT id, name FROM cities ORDER BY sort_order, id"))
        cities = r.fetchall()
        for city_id, city_name in cities:
            if city_name == "Минск":
                for i, (name, address_val, lat, lon) in enumerate(MINSK_ARENAS):
                    session.execute(
                        text("""
                            UPDATE arenas SET address = CAST(:address_val AS VARCHAR(512)), latitude = :lat, longitude = :lon
                            WHERE city_id = :cid AND name = CAST(:name_val AS VARCHAR(128))
                        """),
                        {"cid": city_id, "name_val": name, "address_val": address_val, "lat": lat, "lon": lon},
                    )
                    session.execute(
                        text("""
                            INSERT INTO arenas (city_id, name, sort_order, address, latitude, longitude)
                            SELECT :cid, CAST(:name_val AS VARCHAR(128)), :ord,
                                   CAST(:address_val AS VARCHAR(512)), :lat, :lon
                            WHERE NOT EXISTS (SELECT 1 FROM arenas WHERE city_id = :cid AND name = CAST(:name_val AS VARCHAR(128)))
                        """),
                        {"cid": city_id, "name_val": name, "ord": i, "address_val": address_val, "lat": lat, "lon": lon},
                    )
            else:
                for i, name in enumerate([f"Арена 1 ({city_name})", f"Арена 2 ({city_name})"]):
                    address_val = f"Беларусь, {city_name}"
                    session.execute(
                        text("""
                            INSERT INTO arenas (city_id, name, sort_order, address)
                            SELECT :cid, CAST(:name_val AS VARCHAR(128)), :ord, CAST(:address_val AS VARCHAR(512))
                            WHERE NOT EXISTS (SELECT 1 FROM arenas WHERE city_id = :cid AND name = CAST(:name_val AS VARCHAR(128)))
                        """),
                        {"cid": city_id, "name_val": name, "ord": i, "address_val": address_val},
                    )
        session.commit()
    print("Arenas seeded.")


if __name__ == "__main__":
    main()
