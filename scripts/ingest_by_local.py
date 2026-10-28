"""Один прогон источников, которым нужен белорусский IP: СДЮШОР, Горки, Бобруйск, Солигорск,
Конькобежный стадион, Минск Арена.

С Railway эти сайты не открываются (таймаут или 403), поэтому их задания в проде выключены. Здесь они
запускаются с ноутбука в Беларуси, **не меняя** ``is_enabled`` в базе: прогон идёт по списку
``parser_key`` независимо от флага, а результат ложится в те же таблицы (слоты, прогоны, состояние
источника), что и у планировщика, поэтому админка «Источники расписаний» видит свежие даты.

Запуск (VPN выключен, из корня репозитория, Railway CLI залогинен):

  bash scripts/run_ice_ingest_prod_local.sh scripts/ingest_by_local.py --i-know-this-is-prod
  ... --only gorki_lds_v1 bobruisk_arena_v1      # только эти источники
  ... --dry-run                                  # показать, что будет запущено, и выйти

Перед прогоном проверяется страна текущего IP (ipinfo.io): не Беларусь — скрипт останавливается,
чтобы не записать в базу пустые ответы. Если задан ``BY_EGRESS_PROXY_URL`` (локальный tinyproxy), он
используется для заданий с ``requires_by_egress``; иначе они ходят напрямую с этого компьютера.

Юность (``junost_instagram_caption_v1``) здесь не участвует: её расписание берётся из подписи в
Instagram вручную, см. docs/instructions/ice-ingest-junost-instagram.md.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    warn_prod_ack,
)

# parser_key → понятное имя (для вывода). Состав — те задания, что на Railway не работают без BY IP.
BY_ONLY_SOURCES: dict[str, str] = {
    "ledlife_origin_html_v1": "СДЮШОР по фигурному катанию (Минск)",
    "gorki_lds_v1": "Ледовый дворец, Горки",
    "bobruisk_arena_v1": "Бобруйск-арена",
    "soligorsk_szk_v1": "Спортивно-зрелищный комплекс, Солигорск",
    "minskarena_speed_oval_v1": "Конькобежный стадион, Минск",
    "minskarena_main_saleframe_v1": "Минск Арена",
}


def current_ip_country(timeout: float = 10.0) -> str | None:
    """Страна текущего исходящего IP (``BY``, ``RU``…) или None, если узнать не удалось."""
    try:
        with urllib.request.urlopen("https://ipinfo.io/country", timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode().strip().upper() or None
    except Exception:  # noqa: BLE001 — нет сети/сервис лежит: пусть решает вызывающий
        return None


def select_keys(only: list[str] | None) -> list[str]:
    """Ключи к запуску: все из ``BY_ONLY_SOURCES`` или явный список (неизвестные — ошибка)."""
    if not only:
        return list(BY_ONLY_SOURCES)
    unknown = [k for k in only if k not in BY_ONLY_SOURCES]
    if unknown:
        raise SystemExit(
            "Неизвестные parser_key: " + ", ".join(unknown) + ". Доступны: " + ", ".join(BY_ONLY_SOURCES)
        )
    return list(dict.fromkeys(only))


async def _run(keys: list[str], *, dry_run: bool) -> int:
    from sqlalchemy import text

    from src.application.schedule_waves import parser_wave_recorder
    from src.infrastructure.db.session import async_session_factory, engine
    from src.ingestion.jobs import SqlAlchemyParserJobStore
    from src.ingestion.parsers import default_registry
    from src.ingestion.publish import SqlAlchemyIceSessionPublisher
    from src.ingestion.scheduler import IceIngestScheduler
    from src.ingestion.scheduler_lock import run_with_ice_ingest_lock
    from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
    from src.ingestion.types import RUN_STATUS_OK

    class SelectedJobsStore(SqlAlchemyParserJobStore):
        """Отдаёт задания по ``parser_key`` вне зависимости от ``is_enabled`` и ``next_run_at``."""

        async def list_due(self, now: datetime):  # noqa: ARG002
            placeholders = ", ".join(f":k{i}" for i in range(len(keys)))
            rows = await self._session.execute(
                text(
                    f"""
                    SELECT j.id, j.arena_id, j.parser_key, j.is_enabled, j.cadence,
                           j.next_run_at, j.last_run_at, j.config, j.notes,
                           j.last_ok_at, j.last_ok_slot_count, j.failing_since, j.failure_streak,
                           j.last_error_code, j.last_error_summary, j.alert_state, j.alert_sent_at,
                           ap.timezone AS arena_timezone
                    FROM ice_parser_jobs j
                    LEFT JOIN arena_profiles ap ON ap.arena_id = j.arena_id
                    WHERE j.parser_key IN ({placeholders})
                    ORDER BY j.arena_id
                    """
                ),
                {f"k{i}": k for i, k in enumerate(keys)},
            )
            from src.ingestion.jobs import job_from_row

            return [job_from_row(r) for r in rows.fetchall()]

    settings = Settings()
    proxy = settings.by_egress_proxy_url or None

    async def run_jobs():
        async with async_session_factory() as session:
            scheduler = IceIngestScheduler(
                store=SelectedJobsStore(session),
                recorder=SqlAlchemyScrapeRunRecorder(session),
                registry=default_registry(),
                publisher=SqlAlchemyIceSessionPublisher(session),
                checkpoint=session.commit,
                job_savepoint=session.begin_nested,
                schedule_wave_recorder=parser_wave_recorder(async_session_factory),
                by_egress_proxy_url=proxy,
                by_egress_configured=True,  # мы уже проверили, что IP белорусский (или идём через BY-прокси)
                max_jobs_per_tick=None,
                tick_budget_s=None,
            )
            if dry_run:
                jobs = await scheduler._store.list_due(datetime.now(timezone.utc))  # noqa: SLF001
                for job in jobs:
                    print(
                        f"[dry-run] arena_id={job.arena_id} {job.parser_key} "
                        f"(is_enabled={job.is_enabled}, requires_by_egress={job.config.get('requires_by_egress', False)})"
                    )
                missing = [k for k in keys if k not in {j.parser_key for j in jobs}]
                for k in missing:
                    print(f"[dry-run] ВНИМАНИЕ: в ice_parser_jobs нет задания {k}")
                return []
            outcomes = await scheduler.run_due(datetime.now(timezone.utc))
            await session.commit()
            return outcomes

    acquired, outcomes = await run_with_ice_ingest_lock(engine, run_jobs)
    if not acquired:
        print("Планировщик на Railway сейчас держит блокировку ингеста — повторите через минуту.")
        return 2
    bad = 0
    for record in outcomes:
        ok = record.status == RUN_STATUS_OK
        bad += 0 if ok else 1
        extracted = record.slot_count + record.slots_dropped
        print(
            f"{'OK  ' if ok else 'FAIL'} arena_id={record.arena_id} {record.parser_key} status={record.status} "
            f"http={record.http_status if record.http_status is not None else '-'} "
            f"extracted={extracted} published={record.slot_count if ok else 0} "
            f"{record.error_code or ''} {record.error_message or ''}".rstrip()
        )
    if outcomes:
        print(f"Готово: {len(outcomes) - bad} из {len(outcomes)} успешно.")
    return 1 if bad else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_i_know_this_is_prod_argument(parser)
    parser.add_argument("--only", nargs="+", metavar="PARSER_KEY", help="только эти parser_key")
    parser.add_argument("--dry-run", action="store_true", help="показать задания и выйти, ничего не запуская")
    parser.add_argument("--skip-ip-check", action="store_true", help="не проверять страну IP (только для отладки)")
    args = parser.parse_args()

    keys = select_keys(args.only)
    url = Settings().database_url
    assert_database_url(url, apply=True, allow_prod=args.i_know_this_is_prod)
    if args.i_know_this_is_prod:
        assert_railway_target_database(url)
        warn_prod_ack()

    if not args.dry_run and not args.skip_ip_check:
        country = current_ip_country()
        if country != "BY":
            sys.exit(
                f"Текущий IP: {country or 'не удалось определить'} — нужна Беларусь (BY). "
                "Выключите VPN и повторите. Иначе сайты арен снова ответят таймаутом."
            )
        print("IP: BY — можно запускать.")

    print("Источники:", ", ".join(f"{k} ({BY_ONLY_SOURCES[k]})" for k in keys))
    sys.exit(asyncio.run(_run(keys, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
