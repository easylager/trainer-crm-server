"""Локальный каталог «как в проде»: все катки Минска (+ регионы), магазины, заточки, расписания.

Зачем. Загрузчики каталога (досье катков, задания парсеров, фикстуры) ключуются по
prod-id арен (``data/minsk-arenas-prod.csv``: Минск-Арена = 2, Замок = 3, …). В локальной
базе разработчика этих арен обычно нет или они под другими id — и каждый загрузчик
молча пропускает «чужие» строки. Этот скрипт сначала заводит Минск и его катки под теми
же id, что в проде, а потом по очереди запускает уже существующие загрузчики.

Только локальная база (localhost, trainer_crm / trainer_crm_test). Прод не трогает и
флага для прода нет: в проде арены уже есть, там запускаются сами загрузчики.

По умолчанию — план без записи. Запись — ``--apply``.

  PYTHONPATH=. python scripts/bootstrap_local_catalog.py
  PYTHONPATH=. python scripts/bootstrap_local_catalog.py --apply --geocode

Шаги после заведения арен (каждый — отдельный скрипт, можно запускать и руками):
  1. seed_regional_arenas.py --apply          катки областей (Брест, Гомель, …)
  2. load_minsk_arena_cards.py --apply        досье минских катков: часы, цены, фото, телефоны
  3. seed_ice_parser_jobs.py --apply          парсеры расписаний Минска
  4. seed_regional_ice_parser_jobs.py --apply парсеры расписаний областей
  5. load_catalog_shops.py --apply --allow-local-dev-db   магазины и заточки из data/catalog/shops-minsk.json
  6. load_catalog_shops.py --file data/catalog/rinks-minsk.json --apply   пропущенные катки
  7. run_ice_ingest_once.py                   прочитать расписания сайтов прямо сейчас
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import ProgrammingError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.shared import minsk_speed_oval as speed_oval  # noqa: E402
from src.shared.config import Settings  # noqa: E402
from src.shared.ops_db_guard import assert_database_url  # noqa: E402

MINSK_CSV = ROOT / "data" / "minsk-arenas-prod.csv"
MINSK = "Минск"
MINSK_PROD_CITY_ID = 2


def _database_url() -> str:
    settings = Settings()
    url = settings.database_url_sync or settings.database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def migrations_behind(url: str) -> str | None:
    """«0210 → 0211», если база отстаёт от кода; None — всё на месте.

    Загрузчики и разовый прогон парсеров читают новые колонки (0211: last_ok_at и т.д.) —
    на отставшей базе они падают в середине прогона, после половины записей.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    heads = set(ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads())
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            current = {row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version"))}
    except ProgrammingError:  # нет таблицы версий: база не создана миграциями
        current = set()
    finally:
        engine.dispose()
    if current == heads:
        return None
    return f"{', '.join(sorted(current)) or 'пусто'} → {', '.join(sorted(heads))}"


def minsk_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with MINSK_CSV.open(encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            rows.append(
                {
                    "id": int(raw["arena_id"]),
                    "name": raw["name"].strip(),
                    "address": raw["address"].strip() or None,
                    "lat": float(raw["latitude"]) if raw["latitude"] else None,
                    "lon": float(raw["longitude"]) if raw["longitude"] else None,
                    # Лыжероллерная трасса — не лёд (реестр парсеров: target=not_ice).
                    "venue_type": "outdoor" if "лыжероллер" in raw["name"].lower() else "ice",
                }
            )
    rows.append(
        {
            "id": speed_oval.ARENA_ID,
            "name": speed_oval.NAME,
            "address": speed_oval.ADDRESS,
            "lat": speed_oval.LATITUDE,
            "lon": speed_oval.LONGITUDE,
            "venue_type": "ice",
        }
    )
    return rows


def ensure_minsk(session: Session, *, apply: bool) -> tuple[int | None, list[str]]:
    """Минск в локальной базе: по имени, иначе с prod-id 2, иначе с новым id."""
    notes: list[str] = []
    found = session.execute(text("SELECT id FROM cities WHERE name = :n ORDER BY id LIMIT 1"), {"n": MINSK}).scalar()
    if found is not None:
        if int(found) != MINSK_PROD_CITY_ID:
            notes.append(f"Минск у вас под id={found}, в проде — {MINSK_PROD_CITY_ID}: арены заведём в ваш id={found}")
        return int(found), notes
    taken = session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": MINSK_PROD_CITY_ID}).scalar()
    if not apply:
        notes.append("Минск будет создан")
        return None, notes
    if taken is None:
        session.execute(
            text("INSERT INTO cities (id, name, sort_order, country, price_group) VALUES (:id, :n, 0, 'BY', 'BY_BASE')"),
            {"id": MINSK_PROD_CITY_ID, "n": MINSK},
        )
        city_id = MINSK_PROD_CITY_ID
    else:
        city_id = session.execute(
            text("INSERT INTO cities (name, sort_order, country, price_group) VALUES (:n, 0, 'BY', 'BY_BASE') RETURNING id"),
            {"n": MINSK},
        ).scalar_one()
        notes.append(f"id={MINSK_PROD_CITY_ID} занят городом «{taken}» — Минск создан под id={city_id}")
    session.execute(
        text("SELECT setval(pg_get_serial_sequence('cities', 'id'), GREATEST((SELECT MAX(id) FROM cities), 1))")
    )
    return int(city_id), notes


def ensure_minsk_arenas(session: Session, city_id: int | None, *, apply: bool) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {"create": [], "ok": [], "conflict": []}
    for row in minsk_rows():
        by_id = session.execute(
            text("SELECT name, city_id FROM arenas WHERE id = :id"), {"id": row["id"]}
        ).first()
        if by_id is not None:
            if str(by_id[0]).strip().lower() == str(row["name"]).lower():
                report["ok"].append(f"#{row['id']} {row['name']}")
            else:
                report["conflict"].append(
                    f"#{row['id']} {row['name']}: этот id у вас занят «{by_id[0]}» — досье и парсер этого катка не загрузятся"
                )
            continue
        same_name = session.execute(
            text("SELECT id FROM arenas WHERE lower(name) = lower(:n) LIMIT 1"), {"n": row["name"]}
        ).scalar()
        if same_name is not None:
            report["conflict"].append(
                f"#{row['id']} {row['name']}: у вас он под id={same_name} — загрузчики ждут id={row['id']}"
            )
            continue
        report["create"].append(f"#{row['id']} {row['name']}")
        if apply and city_id is not None:
            session.execute(
                text(
                    "INSERT INTO arenas (id, city_id, name, address, latitude, longitude, is_active, is_confirmed, venue_type) "
                    "VALUES (:id, :c, :n, :a, :lat, :lon, true, true, :vt)"
                ),
                {"id": row["id"], "c": city_id, "n": row["name"], "a": row["address"],
                 "lat": row["lat"], "lon": row["lon"], "vt": row["venue_type"]},
            )
    if apply:
        session.execute(
            text("SELECT setval(pg_get_serial_sequence('arenas', 'id'), GREATEST((SELECT MAX(id) FROM arenas), 1))")
        )
    return report


def loader_steps(*, geocode: bool, ingest: bool) -> list[tuple[str, list[str]]]:
    geo = ["--geocode"] if geocode else []
    steps = [
        ("Катки областей", ["scripts/seed_regional_arenas.py", "--apply"]),
        ("Досье катков Минска", ["scripts/load_minsk_arena_cards.py", "--apply", "--allow-local-dev-db", "--no-report"]),
        ("Парсеры Минска", ["scripts/seed_ice_parser_jobs.py", "--apply"]),
        ("Парсеры областей", ["scripts/seed_regional_ice_parser_jobs.py", "--apply"]),
        ("Магазины и заточки", ["scripts/load_catalog_shops.py", "--apply", "--allow-local-dev-db", *geo]),
        ("Пропущенные катки", ["scripts/load_catalog_shops.py", "--file", "data/catalog/rinks-minsk.json",
                               "--apply", "--allow-local-dev-db", *geo]),
    ]
    if ingest:
        steps.append(("Расписания с сайтов", ["scripts/run_ice_ingest_once.py"]))
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Локальный каталог как в проде (только локальная база).")
    parser.add_argument("--apply", action="store_true", help="Записать (иначе — только план).")
    parser.add_argument("--geocode", action="store_true", help="Координаты магазинов и новых катков через Nominatim.")
    parser.add_argument("--no-ingest", action="store_true", help="Не читать расписания сайтов в конце.")
    args = parser.parse_args(argv)

    url = _database_url()
    behind = migrations_behind(url)
    if behind:
        print(f"База не на последней миграции ({behind}). Сначала: alembic upgrade head", file=sys.stderr)
        return 2
    # Без флага прода: assert_database_url отказывает облачным хостам и чужим именам баз.
    assert_database_url(url, apply=True)

    engine = create_engine(url)
    with Session(engine) as session:
        city_id, notes = ensure_minsk(session, apply=args.apply)
        report = ensure_minsk_arenas(session, city_id, apply=args.apply)
        if args.apply:
            session.commit()
    for note in notes:
        print(f"  · {note}")
    print(f"Катки Минска: создать {len(report['create'])}, уже есть {len(report['ok'])}, конфликтов {len(report['conflict'])}")
    for line in report["create"]:
        print(f"  + {line}")
    for line in report["conflict"]:
        print(f"  ! {line}")

    steps = loader_steps(geocode=args.geocode, ingest=not args.no_ingest)
    if not args.apply:
        print("\nDry-run: ничего не записано. С --apply дальше пойдут шаги:")
        for title, cmd in steps:
            print(f"  {title}: python {' '.join(cmd)}")
        return 0

    env = dict(os.environ, PYTHONPATH=str(ROOT))
    settings = Settings()
    if not (settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key) and not settings.local_storage_path:
        # Без S3 фото катков и магазинов иначе просто пропустятся. Локальная папка — то,
        # что API отдаёт сам, если в .env стоит тот же LOCAL_STORAGE_PATH.
        env["LOCAL_STORAGE_PATH"] = str(ROOT / "var" / "media")
        print(f"\nS3 не настроен: фото сохраним в {env['LOCAL_STORAGE_PATH']}.")
        print("Чтобы API их показывал, добавьте в .env: LOCAL_STORAGE_PATH=var/media")
    failed: list[str] = []
    for title, cmd in steps:
        print(f"\n=== {title}: python {' '.join(cmd)}")
        code = subprocess.call([sys.executable, *cmd], cwd=ROOT, env=env)
        if code != 0:
            failed.append(f"{title} (код {code})")
    print("\nГотово." if not failed else "\nГотово с ошибками: " + "; ".join(failed))
    print("Что осталось пустым: PYTHONPATH=. python scripts/catalog_coverage_report.py --city Минск")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
