"""Regional (non-Minsk) BY ice arenas: cities + arenas + arena_profiles skeleton.

Source of facts: `.ai/data/by-arenas-prod.csv` (read-only prod census dump — names,
addresses, coordinates only; no client/business data). This script writes to local
dev/test Postgres after `--apply`. Cloud/Railway needs `--apply --i-know-this-is-prod`.

Arena ids are chosen to match the prod census (and therefore the existing
`.ai/data/fixtures/*/expected.json` + `.ai/parsers/*.md` specs) so fixtures, tests
and seed data all reference the same arena_id. Safe: none of these ids collide
with the current local dev DB (checked before insert).

Default is dry-run. ``--apply`` writes to a local test/dev DB.
Cloud/Railway requires ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/seed_regional_arenas.py
  PYTHONPATH=. python scripts/seed_regional_arenas.py --apply
  PYTHONPATH=. python scripts/seed_regional_arenas.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)


def _assert_local_database(url: str, *, apply: bool, allow_prod: bool = False) -> None:
    assert_database_url(url, apply=apply, allow_prod=allow_prod)


# (city_name, sort_order) — new cities beyond the 4 already seeded locally (Минск, Гомель, Москва/МО, СПб).
NEW_CITIES: list[tuple[str, int]] = [
    ("Барановичи", 10), ("Береза", 11), ("Бобруйск", 12), ("Брест", 13),
    ("Витебск", 14), ("Горки", 15), ("Гродно", 16), ("Жодино", 17),
    ("Ивацевичи", 18), ("Кобрин", 19), ("Лида", 20), ("Лунинец", 21),
    ("Могилёв", 22), ("Молодечно", 23), ("Новополоцк", 24), ("Орша", 25),
    ("Островец", 26), ("Пинск", 27), ("Пружаны", 28), ("Раубичи", 29),
    ("Силичи", 30), ("Солигорск", 31), ("Шклов", 32),
]

# arena_id (matches prod census + fixtures/expected.json), city_name, arena name, address, lat, lon, slug, has_parser
ARENAS: list[tuple[int, str, str, str, float, float, str, bool]] = [
    (23, "Барановичи", "Ледовый дворец спорта", "Советский проспект, 20", 53.1493182, 26.0014462, "baranovichi-lds", True),
    (26, "Береза", "Ледовая арена", "ул. 17 Сентября, 39", 52.5299, 24.98099, "bereza-lds", False),
    (38, "Бобруйск", "Бобруйск-арена", "Карбышева 11", 53.1423013, 29.2469144, "bobruisk-arena", True),
    (22, "Брест", "Брестский ледовый дворец спорта", "ул. Московская, 151", 52.0926764, 23.7384897, "brest-lds", True),
    (29, "Витебск", "Дворец спорта", "проспект Строителей 23", 55.1692254, 30.2266233, "vitebsk-ds", True),
    (32, "Горки", "Ледовый дворец", "Вокзальная улица 23", 54.2747969, 30.9993037, "gorki-lds", True),
    (10, "Гродно", "ТЦ «Тринити»", "проспект Янки Купалы 87", 53.649866, 23.854538, "grodno-triniti", True),
    (11, "Гродно", "Ледовый дворец спорта", "ул. Коммунальная 3а", 53.68819, 23.824166, "grodno-neman", True),
    (20, "Жодино", "Ледовая площадка ГУ СДЮШОР", "ул. Лебедевского, 18", 54.0942605, 28.3262757, "zhodino-sdyushor", False),
    (28, "Ивацевичи", "Ледовая арена", "Спортивная 3", 52.7211098, 25.3303487, "ivatsevichi-lds", False),
    (25, "Кобрин", "Ледовая арена", "Замковая площадь 11А", 52.2136574, 24.3641108, "kobrin-lds", True),
    (37, "Лида", "Ледовый дворец", "Качана 31", 53.8954462, 25.3237632, "lida-lds", True),
    (40, "Лунинец", "СК Олимп-2011", "Красная улица 160Б", 52.2600712, 26.7899673, "luninets-olimp", False),
    (43, "Могилёв", "Дворец спорта «Могилёв»", "ул. Гагарина 1", 53.88464, 30.32903, "mogilev-ds", True),
    (18, "Молодечно", "Спортивно-развлекательный центр", "ул. Великий Гостинец, 102", 54.3011204, 26.8650159, "molodechno-src", False),
    (30, "Новополоцк", "Ледовый дворец", "ул. Молодёжная, 94Б", 55.5069684, 28.7024495, "novopolotsk-lds", True),
    (31, "Орша", "Ледовая арена", "ул. Владимира Ленина, 79", 54.5217761, 30.4381153, "orsha-arena", True),
    (41, "Островец", "Ледовая площадка", "Октябрьская улица 39", 54.6101379, 25.9612152, "ostrovets-lds", True),
    (24, "Пинск", "Ледовая арена УСК «Волна»", "ул. Иркутско-Пинской дивизии, 46", 52.1221795, 26.1277244, "pinsk-volna", True),
    (27, "Пружаны", "Ледовая арена ГУ СДЮШОР №2", "ул. Заводская, 15", 52.5663378, 24.4743121, "pruzhany-sdyushor", False),
    (15, "Раубичи", "РЦОП по зимним видам спорта", "Минский район, Острошицко-Городской сельсовет", 54.0628, 27.7354, "raubichi-rcop", False),
    (16, "Силичи", "Крытый каток РГЦ «Силичи»", "Минская обл., Логойский р-н, РГЦ «Силичи»", 54.1565, 27.8349, "silichi-rgc", False),
    (19, "Солигорск", "Спортивно-зрелищный комплекс", "ул. К. Заслонова, 25", 52.7909489, 27.5366473, "soligorsk-szk", True),
    (42, "Шклов", "Ледовая арена", "ул. Почтовая 2", 54.2044194, 30.3049466, "shklov-arena", True),
    (33, "Гомель", "Гомельский ледовый дворец спорта", "ул. Мазурова, 110", 52.4604315, 31.0219016, "gomel-lds", True),
]


def _database_url() -> str:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def _print_plan() -> None:
    print(f"Cities to ensure: {len(NEW_CITIES)}")
    print(f"Arenas to ensure: {len(ARENAS)} (parser-ready: {sum(1 for a in ARENAS if a[7])})")
    for arena_id, city, name, *_rest, slug, has_parser in ARENAS:
        flag = "parser" if has_parser else "profile-only"
        print(f"  arena_id={arena_id:>3} [{flag:12}] {city} — {name} (slug={slug})")


def run(*, apply: bool, allow_prod: bool = False) -> None:
    url = _database_url()
    _assert_local_database(url, apply=apply, allow_prod=allow_prod)
    if allow_prod:
        warn_prod_ack()
    if not apply:
        _print_plan()
        print("\nDry-run only. Re-run with --apply to write.")
        return

    engine = create_engine(url)
    with Session(engine) as session:
        city_ids: dict[str, int] = {}
        row = session.execute(text("SELECT id, name FROM cities"))
        for cid, name in row.fetchall():
            city_ids[name] = cid

        for name, sort_order in NEW_CITIES:
            if name in city_ids:
                continue
            result = session.execute(
                text("INSERT INTO cities (name, sort_order, country, price_group) "
                     "VALUES (:name, :ord, 'BY', 'BY_BASE') RETURNING id"),
                {"name": name, "ord": sort_order},
            )
            city_ids[name] = result.scalar_one()
            print(f"city created: {name} -> id={city_ids[name]}")

        for arena_id, city, name, address, lat, lon, slug, has_parser in ARENAS:
            city_id = city_ids[city]
            existing = session.execute(
                text("SELECT id FROM arenas WHERE id = :aid"), {"aid": arena_id}
            ).scalar_one_or_none()
            if existing is not None:
                print(f"arena {arena_id} already exists, skipping arena insert")
            else:
                session.execute(
                    text(
                        "INSERT INTO arenas (id, city_id, name, address, latitude, longitude, "
                        "is_active, is_confirmed) "
                        "VALUES (:id, :city_id, :name, :address, :lat, :lon, true, true)"
                    ),
                    {"id": arena_id, "city_id": city_id, "name": name, "address": address, "lat": lat, "lon": lon},
                )
                print(f"arena created: id={arena_id} {city} — {name}")

            profile_exists = session.execute(
                text("SELECT 1 FROM arena_profiles WHERE arena_id = :aid"), {"aid": arena_id}
            ).scalar_one_or_none()
            if profile_exists is not None:
                print(f"arena_profile {arena_id} already exists, skipping")
                continue
            session.execute(
                text(
                    "INSERT INTO arena_profiles (arena_id, city_id, slug, district, timezone, "
                    "status, amenities, social_urls) "
                    "VALUES (:aid, :city_id, :slug, :district, 'Europe/Minsk', 'published', "
                    "'{}'::jsonb, '{}'::jsonb)"
                ),
                {"aid": arena_id, "city_id": city_id, "slug": slug, "district": city},
            )
            print(f"arena_profile created: arena_id={arena_id} slug={slug}")

        # Bump the arenas PK sequence past any explicit ids we just inserted.
        session.execute(
            text("SELECT setval(pg_get_serial_sequence('arenas', 'id'), "
                 "GREATEST((SELECT MAX(id) FROM arenas), 1))")
        )
        session.commit()
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    run(apply=args.apply, allow_prod=args.i_know_this_is_prod)


if __name__ == "__main__":
    main()
