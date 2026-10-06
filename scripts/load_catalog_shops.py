"""TASK-146: загрузить ледовые магазины и мастерские из data/catalog/shops-<город>.json.

По умолчанию — dry-run: печатает план (что создаст, что обновит, где заточка у катков)
и ничего не пишет. ``--apply`` пишет в локальную тестовую БД; облачная/прод — только
с ``--apply --i-know-this-is-prod``.

``--geocode`` — координаты по адресу через Nominatim (нужен выход в интернет; не чаще
1 запроса в секунду — правило Nominatim). Без него места создаются без координат: они
есть в списке каталога и на своих страницах, но не на карте.

Usage:
  PYTHONPATH=. python scripts/load_catalog_shops.py
  PYTHONPATH=. python scripts/load_catalog_shops.py --apply --geocode
  PYTHONPATH=. python scripts/load_catalog_shops.py --apply --geocode --i-know-this-is-prod
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.load_minsk_arena_cards import (  # noqa: E402
    assert_local_database_url,
    async_database_url,
    resolve_database_url,
)
from src.application.catalog_shops_import import (  # noqa: E402
    ShopImportError,
    apply_plan,
    build_plan,
    parse_shops_file,
)
from src.shared.minsk_speed_oval import ARENA_ID as SPEED_OVAL_ARENA_ID  # noqa: E402
from src.shared.ops_db_guard import add_i_know_this_is_prod_argument, warn_prod_ack  # noqa: E402

DEFAULT_FILE = ROOT / "data" / "catalog" / "shops-minsk.json"
USER_AGENT = "GlideCatalogImport/1.0 (+https://glide.by)"


def make_geocoder():
    import httpx

    from scripts.geocode_arena_addresses import _build_search_query, geocode_nominatim

    client = httpx.Client(timeout=15)
    last = [0.0]

    async def geocode(address: str, city: str):
        wait = 1.1 - (time.monotonic() - last[0])
        if wait > 0:
            await asyncio.sleep(wait)
        last[0] = time.monotonic()
        try:
            return geocode_nominatim(
                client,
                query=_build_search_query(address, city),
                user_agent=USER_AGENT,
                sleep_between_retries=1.1,
            )
        except Exception as exc:  # noqa: BLE001 — один адрес не должен ронять импорт
            print(f"  ! geocode failed for {address!r}: {exc}", file=sys.stderr)
            return None

    return geocode


def print_plan(plan) -> None:
    print(f"Город: {plan.city_name} (#{plan.city_id})")
    print(f"Создать: {len(plan.creates)}")
    for rec in plan.creates:
        services = ", ".join(k for k, v in rec.amenities.items() if v)
        print(f"  + {rec.name} — {rec.display_address or 'без адреса'} [{services}]")
    print(f"Обновить: {len(plan.updates)}")
    for arena_id, rec in plan.updates:
        revived = " (вернуть из архива)" if arena_id in plan.revives else ""
        print(f"  ~ #{arena_id} {rec.name}{revived}")
    pending = [rec for rec in plan.creates + [r for _, r in plan.updates] if rec.hours_pending]
    for rec in pending:
        print(f"  ! без часов: {rec.name} — {rec.hours_pending}")
    print(f"Заточка на катках: {len(plan.rink_updates)}")
    for arena_id, note in plan.rink_updates:
        print(f"  ✓ #{arena_id} {note}")
    for problem in plan.rink_problems:
        print(f"  ? {problem}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--apply", action="store_true", help="Записать в БД (иначе — только план).")
    parser.add_argument("--geocode", action="store_true", help="Координаты по адресу через Nominatim.")
    parser.add_argument(
        "--revive",
        action="store_true",
        help=(
            "Вернуть из архива: если активной записи нет, а архивная (is_active=false) "
            "совпала по имени или match — она становится активной и подтверждённой, профиль "
            "публикуется, затем дополняется из файла. Без флага такие записи пропускаются."
        ),
    )
    parser.add_argument(
        "--allow-local-dev-db",
        action="store_true",
        help="Разрешить --apply в локальную базу trainer_crm (облако по-прежнему запрещено).",
    )
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()

    try:
        city, records, rink_rules = parse_shops_file(args.file)
    except ShopImportError as exc:
        print(f"Файл не прошёл проверку: {exc}", file=sys.stderr)
        return 2

    db_url = resolve_database_url()
    assert_local_database_url(
        db_url,
        apply=args.apply,
        allow_local_dev=args.allow_local_dev_db,
        allow_prod=args.i_know_this_is_prod,
    )
    if args.i_know_this_is_prod:
        warn_prod_ack()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(async_database_url(db_url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            try:
                plan = await build_plan(
                    session,
                    city_name=city,
                    records=records,
                    rink_rules=rink_rules,
                    speed_oval_arena_id=SPEED_OVAL_ARENA_ID,
                    revive=args.revive,
                )
            except ShopImportError as exc:
                print(f"Не получится загрузить: {exc}", file=sys.stderr)
                return 2
            print_plan(plan)
            if not args.apply:
                print("\nDry-run: ничего не записано. Добавьте --apply.")
                return 0
            report = await apply_plan(session, plan, geocode=make_geocoder() if args.geocode else None)
            await session.commit()
    finally:
        await engine.dispose()

    print("\nГотово.")
    for key, title in (("created", "Создано"), ("updated", "Обновлено"), ("rinks", "Каткам")):
        for line in report[key]:
            print(f"  {title}: {line}")
    if report["not_on_map"]:
        print("  Без координат (не на карте): " + ", ".join(report["not_on_map"]))
    for line in report.get("photos") or []:
        print(f"  ! {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
