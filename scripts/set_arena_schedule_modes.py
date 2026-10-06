"""TASK-204: set arena schedule_mode for rinks without online schedule (census TASK-155).

Default is dry-run inside a READ ONLY transaction. Apply needs ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/set_arena_schedule_modes.py
  DATABASE_URL=<prod> PYTHONPATH=. python scripts/set_arena_schedule_modes.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    normalize_db_url,
    warn_prod_ack,
)


@dataclass(frozen=True)
class ArenaModeSpec:
    arena_id: int
    mode: str
    reopen_date: date | None = None
    note: str | None = None


# Reviewed against census by-indoor-rinks-2026-10 (TASK-155).
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
    ArenaModeSpec(16, SCHEDULE_MODE_SEASON_CLOSED, reopen_date=date(2026, 3, 25), note="закрыт с 25.03.2026"),
)


async def plan_updates(session: AsyncSession) -> list[str]:
    lines: list[str] = []
    for spec in SPECS:
        row = (
            await session.execute(
                text(
                    """
                    SELECT a.name, p.schedule_mode, p.reopen_date, p.schedule_mode_note
                    FROM arenas a
                    LEFT JOIN arena_profiles p ON p.arena_id = a.id
                    WHERE a.id = :id
                    """
                ),
                {"id": spec.arena_id},
            )
        ).mappings().first()
        if row is None:
            lines.append(f"#{spec.arena_id} SKIP — arena not found")
            continue
        cur_mode = (row.get("schedule_mode") or "auto").strip()
        cur_note = (row.get("schedule_mode_note") or "").strip() or None
        cur_reopen = row.get("reopen_date")
        target_note = spec.note
        if (
            cur_mode == spec.mode
            and cur_reopen == spec.reopen_date
            and (cur_note or None) == (target_note or None)
        ):
            lines.append(f"#{spec.arena_id} {row['name']}: already {spec.mode}")
            continue
        extra = ""
        if spec.reopen_date:
            extra = f", reopen={spec.reopen_date.isoformat()}"
        if spec.note:
            extra += f", note={spec.note!r}"
        lines.append(f"#{spec.arena_id} {row['name']}: {cur_mode} -> {spec.mode}{extra}")
    return lines


async def apply_updates(session: AsyncSession) -> None:
    from src.application.arena_profile import apply_admin_arena_profile_patch

    for spec in SPECS:
        row = (
            await session.execute(
                text("SELECT city_id, name FROM arenas WHERE id = :id"),
                {"id": spec.arena_id},
            )
        ).first()
        if row is None:
            continue
        patch: dict[str, object] = {"schedule_mode": spec.mode}
        if spec.mode == SCHEDULE_MODE_SEASON_CLOSED:
            patch["reopen_date"] = spec.reopen_date.isoformat() if spec.reopen_date else None
            patch["schedule_mode_note"] = spec.note
        await apply_admin_arena_profile_patch(session, int(spec.arena_id), patch)


async def run(apply: bool) -> int:
    url = async_database_url()
    engine = create_async_engine(normalize_db_url(url), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        if not apply:
            await session.execute(text("BEGIN READ ONLY"))
        lines = await plan_updates(session)
        for line in lines:
            print(line)
        if apply:
            await apply_updates(session)
            await session.commit()
            print("Applied.")
        else:
            await session.rollback()
            print("Dry-run only (no writes).")
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Set TASK-204 schedule modes for census rinks.")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    assert_database_url()
    if args.apply:
        warn_prod_ack(args)
    return asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
