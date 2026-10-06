"""Проставить режим расписания 10 каткам без онлайн-расписания (TASK-204).

По умолчанию dry-run: печатает план и ничего не пишет. Запись — ``--apply``.
Облачная база — только вместе с ``--i-know-this-is-prod`` (хост проверяется отдельно).

Повторный запуск, когда режимы уже стоят, печатает «already …» и базу не трогает.

  PYTHONPATH=. python scripts/set_arena_schedule_modes.py
  DATABASE_URL=<public> DATABASE_URL_SYNC=<public> PYTHONPATH=. \\
    python scripts/set_arena_schedule_modes.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from src.shared.arena_schedule_mode import (  # noqa: E402
    SCHEDULE_MODE_PHONE,
    SCHEDULE_MODE_SEASON_CLOSED,
)
from src.shared.ops_db_guard import (  # noqa: E402
    ProdDatabaseError,
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    async_database_url,
    normalize_db_url,
    warn_prod_ack,
)


_MINSK = ZoneInfo("Europe/Minsk")


def minsk_today() -> date:
    """Сегодня по Минску. Локально, без импорта src.ingestion: пакет тянет Settings и бота."""
    return datetime.now(_MINSK).date()


class ScheduleModeError(RuntimeError):
    """Спека неверна: в базу ничего не записано."""


class ConnectionSetupError(RuntimeError):
    """Нет адреса базы или ops_db_guard отказал. Текст без URL."""


@dataclass(frozen=True)
class ArenaModeSpec:
    arena_id: int
    mode: str
    reopen_date: date | None = None
    note: str | None = None


# Перепись by-indoor-rinks-2026-10 (TASK-155). У Силичей 25.03.2026 — дата закрытия,
# не открытия: «откроется 25.03» на карточке смотрелось бы в прошлом.
SPECS: tuple[ArenaModeSpec, ...] = (
    ArenaModeSpec(26, SCHEDULE_MODE_PHONE),
    ArenaModeSpec(35, SCHEDULE_MODE_PHONE),
    ArenaModeSpec(28, SCHEDULE_MODE_PHONE),
    ArenaModeSpec(40, SCHEDULE_MODE_PHONE),
    ArenaModeSpec(9, SCHEDULE_MODE_PHONE),
    ArenaModeSpec(27, SCHEDULE_MODE_PHONE),
    ArenaModeSpec(36, SCHEDULE_MODE_PHONE),
    ArenaModeSpec(20, SCHEDULE_MODE_SEASON_CLOSED, note="ремонт"),
    ArenaModeSpec(15, SCHEDULE_MODE_SEASON_CLOSED, note="массовое катание не проводится"),
    ArenaModeSpec(16, SCHEDULE_MODE_SEASON_CLOSED, note="закрыт с 25.03.2026"),
)

_PROFILE_SQL = text(
    """
    SELECT a.name, p.schedule_mode, p.reopen_date, p.schedule_mode_note
    FROM arenas a
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    WHERE a.id = :id
    """
)


def database_url_from_env() -> str:
    raw = (os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        raise ConnectionSetupError(
            "Не задан DATABASE_URL или DATABASE_URL_SYNC — скрипту некуда подключаться."
        )
    return normalize_db_url(raw)


def _guard_message(exc: ProdDatabaseError) -> str:
    """По-русски и без адреса базы: в тексте ProdDatabaseError бывает сам URL."""
    text_ = str(exc).lower()
    if "i-know-this-is-prod" in text_ and "localhost" in text_:
        return (
            "Флаг --i-know-this-is-prod только для облачной базы. "
            "Сейчас адрес указывает на локальный Postgres."
        )
    if "cloud/prod" in text_ or "refusing cloud" in text_:
        return "Это похоже на прод-базу. Без флага --i-know-this-is-prod скрипт к ней не подключается."
    if "non-local" in text_:
        return "Хост базы не локальный. Для облака нужен флаг --i-know-this-is-prod."
    if "apply is limited" in text_:
        return "Запись (--apply) для локальной базы разрешена только в trainer_crm и trainer_crm_test."
    if "unsupported" in text_:
        return "Неподдерживаемая схема адреса базы. Нужен postgresql://."
    return "Подключение к базе отклонено."


def open_engine(*, apply: bool, allow_prod: bool):
    url = database_url_from_env()
    try:
        assert_database_url(url, apply=apply, allow_prod=allow_prod)
        if allow_prod:
            assert_railway_target_database(url)
            warn_prod_ack()
        return create_async_engine(async_database_url(url))
    except ProdDatabaseError as exc:
        raise ConnectionSetupError(_guard_message(exc)) from exc


def reject_past_reopen_dates(specs: Sequence[ArenaModeSpec], *, today: date) -> None:
    past = [spec for spec in specs if spec.reopen_date is not None and spec.reopen_date < today]
    if not past:
        return
    details = ", ".join(f"#{spec.arena_id} {spec.reopen_date:%d.%m.%Y}" for spec in past)
    raise ScheduleModeError(
        f"reopen_date в прошлом (сегодня {today:%d.%m.%Y}, Europe/Minsk): {details}. "
        "В базу ничего не записано."
    )


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _note(value: object) -> str | None:
    if value is None:
        return None
    text_ = str(value).strip()
    return text_ or None


def _matches(row: Mapping[str, object], spec: ArenaModeSpec) -> bool:
    cur_mode = str(row.get("schedule_mode") or "auto").strip() or "auto"
    return (
        cur_mode == spec.mode
        and _as_date(row.get("reopen_date")) == spec.reopen_date
        and _note(row.get("schedule_mode_note")) == _note(spec.note)
    )


async def _load_profile(session: AsyncSession, arena_id: int):
    return (await session.execute(_PROFILE_SQL, {"id": arena_id})).mappings().first()


def _resolve_today(today: date | None) -> date:
    return minsk_today() if today is None else today


async def plan_updates(session: AsyncSession, *, today: date | None = None) -> list[str]:
    day = _resolve_today(today)
    reject_past_reopen_dates(SPECS, today=day)
    lines: list[str] = []
    for spec in SPECS:
        row = await _load_profile(session, spec.arena_id)
        if row is None:
            lines.append(f"#{spec.arena_id} SKIP — arena not found")
            continue
        if _matches(row, spec):
            lines.append(f"#{spec.arena_id} {row['name']}: already {spec.mode}")
            continue
        cur_mode = str(row.get("schedule_mode") or "auto").strip() or "auto"
        extra = ""
        if spec.reopen_date:
            extra = f", reopen={spec.reopen_date.isoformat()}"
        if spec.note:
            extra += f", note={spec.note!r}"
        lines.append(f"#{spec.arena_id} {row['name']}: {cur_mode} -> {spec.mode}{extra}")
    return lines


async def apply_updates(session: AsyncSession, *, today: date | None = None) -> None:
    day = _resolve_today(today)
    reject_past_reopen_dates(SPECS, today=day)
    from src.application.arena_profile import apply_admin_arena_profile_patch

    for spec in SPECS:
        row = await _load_profile(session, spec.arena_id)
        if row is None or _matches(row, spec):
            continue
        patch: dict[str, object] = {"schedule_mode": spec.mode}
        if spec.mode == SCHEDULE_MODE_SEASON_CLOSED:
            patch["reopen_date"] = spec.reopen_date.isoformat() if spec.reopen_date else None
            patch["schedule_mode_note"] = spec.note
        await apply_admin_arena_profile_patch(session, int(spec.arena_id), patch)


async def execute(
    session: AsyncSession, *, apply: bool, today: date | None = None
) -> list[str]:
    """План и, если ``apply``, запись. То, что делает ``--apply`` после проверки адреса базы."""
    lines = await plan_updates(session, today=today)
    if apply:
        await apply_updates(session, today=today)
    return lines


async def run(*, apply: bool, allow_prod: bool, today: date | None = None) -> None:
    day = today or minsk_today()
    reject_past_reopen_dates(SPECS, today=day)
    engine = open_engine(apply=apply, allow_prod=allow_prod)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            if not apply:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            lines = await execute(session, apply=apply, today=day)
            for line in lines:
                print(line)
            if apply:
                await session.commit()
                print("Applied.")
            else:
                await session.rollback()
                print("Dry-run only (no writes).")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проставить режимы расписания каткам из переписи TASK-155.")
    parser.add_argument("--apply", action="store_true", help="Записать в базу (по умолчанию dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(apply=args.apply, allow_prod=bool(args.i_know_this_is_prod)))
    except ConnectionSetupError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    except ScheduleModeError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
