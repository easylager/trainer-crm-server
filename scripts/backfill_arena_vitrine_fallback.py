"""TASK-119: fallback vitrine profiles for Belarus arenas without a working schedule parser.

For every arena where ``data/ice-parser-status.json`` records ``status: "skip"`` — checked and
confirmed unparseable, not just untried — the arena should still appear in the client catalog as
a real profile (address, photo where one exists) with an honest note and a link to the arena's own
site/community so the user can check the current schedule there. This script is the backfill: it
writes ``website_url`` + ``short_description`` on each arena's ``arena_profiles`` row via
``apply_admin_arena_profile_patch`` (creating the row first if missing).

Two skip-list arena_ids are deliberately excluded — not a schedule problem, a data problem:

- arena_id=12 «Лыжероллерная трасса» — a roller-ski track, not ice. It has no business on the Ice
  Discovery vitrine at all (publishing it here would be worse than leaving it out); it should stay
  a plain trainer-workplace row.
- arena_id=39 «Озёрный» — prod's address/coords put it ~1.3km from arena_id=22 (Брестский ЛДС) and
  hockey.by's own listing conflates «п. Озерный» with Московская 151. This looks like a duplicate
  catalog entry, not two rinks. Giving it its own profile would put a real building on the map
  twice. Left untouched; flagged in TASK-119 as an open question for the owner (merge/deactivate
  is a data-hygiene call outside an ops script's authority).

Default is dry-run (prints the diff, writes nothing). ``--apply`` writes to a local test DB.
Cloud/Railway requires ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/backfill_arena_vitrine_fallback.py
  PYTHONPATH=. python scripts/backfill_arena_vitrine_fallback.py --apply
  PYTHONPATH=. python scripts/backfill_arena_vitrine_fallback.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.arena_profile import apply_admin_arena_profile_patch
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    normalize_db_url,
    warn_prod_ack,
)

# Excluded on purpose — see module docstring.
EXCLUDED_NOT_ICE = 12
EXCLUDED_LIKELY_DUPLICATE = 39


class Fallback(NamedTuple):
    website_url: str | None
    short_description: str


# arena_id -> fallback vitrine copy. Source URLs and reasoning from data/ice-parser-status.json
# (2026-09-06 census, arena "skip" rows), re-verified before writing here.
FALLBACKS: dict[int, Fallback] = {
    9: Fallback(
        "https://olympicarena.by/",
        "Корпоративный каток без публичного расписания массового катания. "
        "Актуальное время уточняйте на сайте арены или по телефону.",
    ),
    13: Fallback(
        "https://justskate.by/",
        "Здесь проводятся тренировки и прокат по записи — открытого массового катания "
        "с расписанием на сайте нет. Запись через сайт клуба.",
    ),
    14: Fallback(
        "https://fint-tm.by/raspisanie-trenirovok/",
        "Хоккейный центр, запись на лёд по телефону — расписание массового катания "
        "на сайте не публикуется.",
    ),
    34: Fallback(
        None,
        "Сезонный каток без сайта с расписанием. Актуальное время массового катания "
        "уточняйте на месте.",
    ),
    18: Fallback(
        "https://src.by/WDKL/ледовая-арена",
        "Расписание на сайте арены сейчас показывает закрытый сезон. Актуальность "
        "проверяйте на сайте перед визитом.",
    ),
    35: Fallback(
        "https://zorzhlobin.by/uslugi/",
        "На сайте арены есть цены, но нет расписания сеансов по времени. "
        "Актуальное время уточняйте на месте или по телефону.",
    ),
    20: Fallback(
        "https://www.xn----8sbkhlnbugdd1c.xn--90ais/расписание-2/",
        "Расписание на сайте арены сейчас показывает закрытый сезон. Актуальность "
        "проверяйте на сайте перед визитом.",
    ),
    36: Fallback(
        None,
        "Официальной страницы с расписанием массового катания не найдено. "
        "Актуальное время уточняйте на месте или по телефону.",
    ),
    26: Fallback(
        "https://hockey.by/icearenas/",
        "Расписание массового катания публикуется в Instagram арены и меняется "
        "каждую неделю — на сайте его нет. Актуальное время смотрите в соцсетях арены.",
    ),
    28: Fallback(
        "https://www.instagram.com/led_arena_basseyn/",
        "Расписание массового катания публикуется в Instagram арены и меняется "
        "каждую неделю — на сайте его нет.",
    ),
    27: Fallback(
        "https://www.pruzhany.brest-region.gov.by/ru/sport-ru/view/2013-07-15-06-52-27-2000001505",
        "Массовое катание проводится ежедневно кроме понедельника, но расписание "
        "по часам публикуется только по телефону — на сайте его нет.",
    ),
    40: Fallback(
        "http://dussch.luninec.edu.by/ru/main.aspx",
        "Публичного расписания массового катания на сайте школы нет. "
        "Актуальное время уточняйте по телефону.",
    ),
    15: Fallback(
        "https://www.rau.by/skates/",
        "По данным сайта массовые катания сейчас не проводятся — это тренировочный "
        "центр зимних видов спорта. Актуальность проверяйте на сайте.",
    ),
    16: Fallback(
        "https://silichy.by/aktualnoe-vremya-raboti",
        "Расписание на сайте комплекса относится к прошлому сезону. Актуальное "
        "время массового катания уточняйте на сайте перед визитом.",
    ),
}


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("Set DATABASE_URL_SYNC or DATABASE_URL")
    return normalize_db_url(raw)


async def run(*, apply: bool, i_know_this_is_prod: bool) -> None:
    url = _db_url()
    assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
    if i_know_this_is_prod:
        warn_prod_ack()

    async_url = url
    if async_url.startswith("postgresql://"):
        async_url = "postgresql+asyncpg://" + async_url[len("postgresql://") :]
    engine = create_async_engine(async_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    filled = 0
    already_filled = 0
    async with Session() as session:
        for arena_id, fallback in sorted(FALLBACKS.items()):
            row = (
                await session.execute(
                    text("SELECT name, is_active FROM arenas WHERE id = :id"),
                    {"id": arena_id},
                )
            ).fetchone()
            if row is None:
                print(f"  [skip] arena_id={arena_id} not found in arenas table")
                continue
            name, is_active = row
            existing = (
                await session.execute(
                    text("SELECT website_url, short_description FROM arena_profiles WHERE arena_id = :id"),
                    {"id": arena_id},
                )
            ).fetchone()
            existing_url = (existing[0] or "").strip() if existing else ""
            existing_desc = (existing[1] or "").strip() if existing else ""

            patch: dict[str, str] = {}
            if not existing_url and fallback.website_url:
                patch["website_url"] = fallback.website_url
            if not existing_desc:
                patch["short_description"] = fallback.short_description

            before = f"website_url={existing_url or None!r} short_description={'set' if existing_desc else None}"
            if not patch:
                already_filled += 1
                print(f"  [already-filled] arena_id={arena_id} {name!r} — {before} — nothing to add, skipping")
                continue
            filled += 1
            flag = "apply" if apply else "dry-run"
            print(f"  [{flag}] arena_id={arena_id} {name!r} active={is_active} — before: {before} — filling: {sorted(patch)}")
            if apply:
                await apply_admin_arena_profile_patch(session, arena_id, patch)
        if apply:
            await session.commit()
            print(f"\nApplied fallback vitrine copy to {filled} arenas ({already_filled} already had both fields — left untouched).")
        else:
            print(f"\nDry-run only — {filled} arenas would gain a field, {already_filled} already fully filled (untouched). Pass --apply to write.")

    print(
        f"\nExcluded on purpose (see module docstring): "
        f"arena_id={EXCLUDED_NOT_ICE} (not ice), arena_id={EXCLUDED_LIKELY_DUPLICATE} (likely duplicate of id=22)."
    )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write to the database (default: dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, i_know_this_is_prod=args.i_know_this_is_prod))


if __name__ == "__main__":
    main()
