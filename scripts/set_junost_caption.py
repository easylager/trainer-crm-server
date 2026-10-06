"""Обновить подпись Instagram для расписания катка «Юность» (arena_id=8).

Парсер ``junost_instagram_caption_v1`` (job id=4) читает текст поста из
``ice_parser_jobs.config->>'caption_text'``. Раньше это правили руками через SQL —
теперь текст разбирается тем же кодом, что и планировщик, а запись идёт одной транзакцией.

Скрипт ничего не пишет без ``--apply``. Сначала он разбирает текст, печатает таблицу
сеансов и отказывается работать, если в посте нет сеансов или все даты уже прошли
(по Europe/Minsk). Работа с прод-БД — только через ``src/shared/ops_db_guard.py``:
``--i-know-this-is-prod`` обязателен для облачного хоста.

Использование (из корня репозитория, где лежит .env — скрипт импортирует настройки приложения):
  # проверить текст (dry-run, в БД ничего не пишет; к прод-БД всё равно нужен --i-know-this-is-prod):
  PYTHONPATH=. .venv/bin/python scripts/set_junost_caption.py --file ~/Desktop/junost-post.txt

  # посмотреть, что лежит в БД (только чтение): будущие сеансы арены 8 и последние запуски job 4:
  PYTHONPATH=. .venv/bin/python scripts/set_junost_caption.py --show --i-know-this-is-prod

  # записать в прод-БД (public URL из Railway):
  DATABASE_URL_SYNC=<public> DATABASE_URL=<public> PYTHONPATH=. .venv/bin/python \
    scripts/set_junost_caption.py --file ~/Desktop/junost-post.txt --apply --i-know-this-is-prod

Инструкция для владельца: docs/ops/junost-caption-update.md
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from src.ingestion.dates import minsk_today  # noqa: E402
from src.ingestion.junost_instagram_caption import (  # noqa: E402
    apply_junost_caption_prices,
    parse_junost_instagram_caption,
)
from src.shared.ops_db_guard import (  # noqa: E402
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    async_database_url,
    normalize_db_url,
    warn_prod_ack,
    ProdDatabaseError,
)

ARENA_ID = 8
JOB_ID = 4
PARSER_KEY = "junost_instagram_caption_v1"


class CaptionError(RuntimeError):
    """Пост нельзя применить: пустой, без сеансов, устаревший или job не тот."""


class ConnectionSetupError(RuntimeError):
    """Не удалось выбрать базу: нет DATABASE_URL или защита ops_db_guard отказала."""


@dataclass(frozen=True)
class ParsedSession:
    local_date: date
    starts_at_local: str
    ends_at_local: str
    adult_minor: int | None
    child_minor: int | None
    rental_minor: int | None


@dataclass(frozen=True)
class CaptionPlan:
    caption: str
    today: date
    sessions: tuple[ParsedSession, ...]

    @property
    def future_sessions(self) -> tuple[ParsedSession, ...]:
        return tuple(session for session in self.sessions if session.local_date >= self.today)


def _to_minor(value: object) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 100))


def build_plan(caption: str, *, today: date | None = None) -> CaptionPlan:
    """Разобрать подпись и отказаться, если применимого расписания в ней нет."""
    cleaned = caption.strip()
    if not cleaned:
        raise CaptionError("Текст поста пустой — вставь подпись целиком.")
    day = today or minsk_today()
    slots = parse_junost_instagram_caption(cleaned, pivot_year=day.year)
    if not slots:
        raise CaptionError(
            "Не нашёл в тексте ни одной пары «дата + время сеанса». "
            "Похоже, формат поста изменился — пришли текст разработчику."
        )
    apply_junost_caption_prices(slots, cleaned)
    sessions = tuple(
        ParsedSession(
            local_date=date.fromisoformat(str(slot.local_date)),
            starts_at_local=str(slot.starts_at_local),
            ends_at_local=str(slot.ends_at_local or ""),
            adult_minor=_to_minor(slot.price_adult),
            child_minor=_to_minor(slot.price_child),
            rental_minor=_to_minor(slot.price_rental),
        )
        for slot in slots
    )
    plan = CaptionPlan(caption=cleaned, today=day, sessions=sessions)
    if not plan.future_sessions:
        dates = ", ".join(sorted({session.local_date.strftime("%d.%m.%Y") for session in sessions}))
        raise CaptionError(
            f"Все сеансы в посте уже прошли ({dates}); сегодня {day:%d.%m.%Y} (Europe/Minsk). "
            "В базу ничего не записано."
        )
    return plan


def _rub(value: int | None) -> str:
    return "—" if value is None else f"{value / 100:.2f}"


def format_plan(plan: CaptionPlan) -> str:
    header = f"{'Дата':<10} {'Начало–конец':<14} {'Взросл.':>8} {'Детск.':>7} {'Прокат':>7}"
    rows = [header, "-" * len(header)]
    future = set(plan.future_sessions)
    for session in plan.sessions:
        past = "" if session in future else "  (прошёл, планировщик отбросит)"
        rows.append(
            f"{session.local_date:%d.%m.%Y}  {session.starts_at_local}–{session.ends_at_local:<8}"
            f"{_rub(session.adult_minor):>8} {_rub(session.child_minor):>7} {_rub(session.rental_minor):>7}{past}"
        )
    return "\n".join(rows)


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        raise ConnectionSetupError(
            "Не задан DATABASE_URL (или DATABASE_URL_SYNC) — скрипту некуда подключаться. "
            "Как получить адрес прод-базы — в docs/ops/junost-caption-update.md."
        )
    return normalize_db_url(raw)


def _open_engine(*, apply: bool, i_know_this_is_prod: bool):
    """Проверить URL защитой ops_db_guard и создать движок (URL нигде не печатается)."""
    url = _db_url()
    try:
        assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
        if i_know_this_is_prod:
            assert_railway_target_database(url)
            warn_prod_ack()
        return create_async_engine(async_database_url(url))
    except ProdDatabaseError as exc:
        raise ConnectionSetupError(_scrub(str(exc), url)) from exc


def _scrub(message: str, url: str) -> str:
    """Не дать адресу базы (с паролем) попасть в сообщение об ошибке."""
    for secret in (url, normalize_db_url(url)):
        message = message.replace(secret, "<DATABASE_URL>")
    return message


async def load_job(session: AsyncSession, *, job_id: int = JOB_ID) -> dict:
    """Прочитать job и убедиться, что это нужный парсер."""
    row = (
        await session.execute(
            text("SELECT id, parser_key, config FROM ice_parser_jobs WHERE id = :id"),
            {"id": job_id},
        )
    ).fetchone()
    if row is None:
        raise CaptionError(f"В ice_parser_jobs нет job id={job_id} — нечего обновлять.")
    found_id, parser_key, config = row
    if str(parser_key) != PARSER_KEY:
        raise CaptionError(
            f"job id={job_id}: parser_key={parser_key!r}, ожидался {PARSER_KEY!r}. "
            "Прерываю — в базу ничего не записано."
        )
    return {"id": int(found_id), "parser_key": str(parser_key), "config": dict(config or {})}


async def write_caption(
    session: AsyncSession,
    *,
    caption: str,
    job_id: int = JOB_ID,
    now: datetime | None = None,
) -> datetime:
    """Проверить job и записать подпись + поставить job в очередь. Коммитит вызывающий."""
    await load_job(session, job_id=job_id)
    stamp = now or datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            UPDATE ice_parser_jobs
            SET config = jsonb_set(COALESCE(config, '{}'::jsonb), '{caption_text}',
                                   to_jsonb(CAST(:caption AS text)), true),
                next_run_at = :now
            WHERE id = :id
            """
        ),
        {"caption": caption, "now": stamp, "id": job_id},
    )
    return stamp


async def run(*, caption: str, apply: bool, i_know_this_is_prod: bool, today: date | None = None) -> None:
    plan = build_plan(caption, today=today)
    print(f"Каток «Юность» (arena_id={ARENA_ID}), job id={JOB_ID} ({PARSER_KEY})")
    print(format_plan(plan))
    print(
        f"\nБудет записано: config.caption_text ({len(plan.caption)} символов) "
        "и next_run_at = now() — планировщик подхватит при следующем тике."
    )

    engine = _open_engine(apply=apply, i_know_this_is_prod=i_know_this_is_prod)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as session:
            if not apply:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            await load_job(session)
            if apply:
                await write_caption(session, caption=plan.caption)
                await session.commit()
                print("\nГотово: подпись записана, job поставлен в очередь.")
            else:
                await session.rollback()
                print("\nDry-run — в базу ничего не записано. Добавь --apply, чтобы записать.")
    finally:
        await engine.dispose()


SHOW_SESSIONS_SQL = """
    SELECT local_date, starts_at_local, ends_at_local,
           price_adult_minor, price_child_minor, price_rental_minor, schedule_basis
    FROM ice_sessions
    WHERE arena_id = :arena_id AND status = 'active' AND local_date >= :today
    ORDER BY starts_at_utc
"""
SHOW_RUNS_SQL = """
    SELECT started_at, status, slots_found
    FROM ice_scrape_runs
    WHERE job_id = :job_id
    ORDER BY started_at DESC
    LIMIT :lim
"""


def format_show(sessions: list[tuple], runs: list[tuple], *, today: date) -> str:
    lines = [f"Будущие сеансы арены {ARENA_ID} (с {today:%d.%m.%Y}, Europe/Minsk):"]
    if not sessions:
        lines.append("  нет — планировщик ещё не собрал сеансы (подожди тик и повтори --show).")
    else:
        header = f"{'Дата':<10} {'Начало–конец':<12} {'Взросл.':>8} {'Детск.':>7} {'Прокат':>7}  основание"
        lines += [header, "-" * len(header)]
        for d, start, end, adult, child, rental, basis in sessions:
            span = f"{start:%H:%M}–{end:%H:%M}"
            lines.append(
                f"{d:%d.%m.%Y} {span:<12} {_rub(adult):>8} {_rub(child):>7} {_rub(rental):>7}  {basis}"
            )
    lines.append(f"\nПоследние запуски парсера (job id={JOB_ID}):")
    if not runs:
        lines.append("  запусков ещё не было.")
    else:
        lines.append(f"{'Начало (UTC)':<18} {'Статус':<10} {'Найдено сеансов':>15}")
        for started, status, found in runs:
            lines.append(f"{started:%d.%m.%Y %H:%M:%S}  {status:<10} {found:>15}")
    return "\n".join(lines)


async def show(*, i_know_this_is_prod: bool, today: date | None = None) -> None:
    """Только чтение: что сейчас лежит в БД по Юности."""
    day = today or minsk_today()
    engine = _open_engine(apply=False, i_know_this_is_prod=i_know_this_is_prod)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            sessions = (
                await session.execute(text(SHOW_SESSIONS_SQL), {"arena_id": ARENA_ID, "today": day})
            ).fetchall()
            runs = (
                await session.execute(text(SHOW_RUNS_SQL), {"job_id": JOB_ID, "lim": 5})
            ).fetchall()
            await session.rollback()
        print(format_show([tuple(r) for r in sessions], [tuple(r) for r in runs], today=day))
    finally:
        await engine.dispose()


def _read_caption(args: argparse.Namespace) -> str:
    if args.file is not None:
        return args.file.read_text(encoding="utf-8")
    if sys.stdin.isatty():
        raise SystemExit("Передай текст поста: --file ПУТЬ или на вход (stdin).")
    return sys.stdin.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, help="Файл с текстом поста (UTF-8). Без него — stdin.")
    parser.add_argument(
        "--show",
        action="store_true",
        help="Только чтение: показать будущие сеансы арены 8 и последние запуски job 4.",
    )
    parser.add_argument("--apply", action="store_true", help="Записать в БД (по умолчанию dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()

    try:
        if args.show:
            if args.apply or args.file is not None:
                parser.error("--show только читает: его нельзя сочетать с --apply и --file.")
            asyncio.run(show(i_know_this_is_prod=args.i_know_this_is_prod))
            return
        caption = _read_caption(args)
        asyncio.run(
            run(caption=caption, apply=args.apply, i_know_this_is_prod=args.i_know_this_is_prod)
        )
    except CaptionError as exc:
        raise SystemExit(f"ОШИБКА: {exc}") from exc
    except ConnectionSetupError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
