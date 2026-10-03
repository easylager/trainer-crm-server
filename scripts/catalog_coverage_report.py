"""TASK-146: отчёт о полноте каталога по городам — что заполнить, чтобы закрыть Беларусь.

Только чтение. По каждому городу печатает:
- сколько мест опубликовано по типам (лёд, зал, магазин…) и сколько не опубликовано;
- катки без парсера расписания и с проблемным парсером (выключен / падает / устарел);
- карточки без координат, фото, часов, телефона, кассы (tickets_url), сайта;
- катки из data/*sources*.csv и data/*arenas*-prod.csv, которых нет в БД;
- магазины из data/catalog/shops-*.json: чего нет в файле и чего нет в БД;
- катки с заточкой из того же файла, которые не нашлись или не отмечены.

Локальная БД — по умолчанию. Прод (только SELECT) — с ``--i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/catalog_coverage_report.py
  PYTHONPATH=. python scripts/catalog_coverage_report.py --city Минск
  PYTHONPATH=. python scripts/catalog_coverage_report.py --country all --json > coverage.json
  PYTHONPATH=. python scripts/catalog_coverage_report.py --i-know-this-is-prod
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.load_minsk_arena_cards import async_database_url, resolve_database_url  # noqa: E402
from src.application.catalog_coverage import (  # noqa: E402
    build_coverage_report,
    coverage_report_as_dict,
    format_coverage_report,
)
from src.shared.ops_db_guard import (  # noqa: E402
    add_i_know_this_is_prod_argument,
    assert_database_url,
    warn_prod_ack,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", help="Только этот город (по имени, без учёта регистра).")
    parser.add_argument(
        "--country",
        default="BY",
        help="Код страны (BY, RU) или 'all'. По умолчанию BY — рынок, который закрываем.",
    )
    parser.add_argument("--json", action="store_true", help="Машиночитаемый вывод вместо текста.")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()

    db_url = resolve_database_url()
    # Отчёт только читает, поэтому apply=False: локальная БД любая, облачная — с флагом.
    assert_database_url(db_url, apply=False, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        warn_prod_ack()

    countries = None if args.country.lower() == "all" else {args.country.upper()}

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(async_database_url(db_url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            report = await build_coverage_report(session, countries=countries, city=args.city)
    finally:
        await engine.dispose()

    if args.json:
        print(json.dumps(coverage_report_as_dict(report), ensure_ascii=False, indent=2, default=str))
    else:
        print(format_coverage_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
