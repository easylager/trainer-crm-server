"""TASK-146: что показываем в каталоге площадок, а что пока нет (решение владельца 2026-10-02).

Скрыть (``arena_profiles.status = 'archived'``, обратимо — вернуть можно ``--show``):
- 13 «JUSTSKATE», 14 «Финт» — пока не показываем;
- каток у Дворца спорта на Немиге — работает только зимой, летом не показываем;
- все площадки ``venue_type = 'gym'`` — залы пока вне каталога.

Показать:
- 12 «Лыжероллерная трасса» — публикуем профиль и грузим фото
  ``data/arena-cards/photos/arena-12/track.jpg``.

Фото. Для любой площадки файлы из ``data/arena-cards/photos/arena-<id>/`` грузятся, если у
площадки ещё нет ни одного кадра (повторный запуск ничего не дублирует). Так на локальный стенд
можно положить кадры «Юности» (8) и «Олимпик-арены» (9), которые на проде уже есть, а в локальной
БД — нет: положи файлы в ``arena-8/`` и ``arena-9/`` и запусти скрипт ещё раз.

По умолчанию dry-run. На прод — только ``--apply --i-know-this-is-prod``.

Usage:
  PYTHONPATH=. python scripts/curate_catalog_visibility.py
  PYTHONPATH=. python scripts/curate_catalog_visibility.py --apply
  PYTHONPATH=. python scripts/curate_catalog_visibility.py --apply --show   # вернуть скрытое
"""
from __future__ import annotations

import argparse
import asyncio
import mimetypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.arena_media import MEDIA_OWNER_ARENA, upload_arena_media_from_bytes
from src.application.arena_profile import (
    ARENA_PROFILE_STATUS_ARCHIVED,
    ARENA_PROFILE_STATUS_PUBLISHED,
    apply_admin_arena_profile_patch,
)
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    normalize_db_url,
    warn_prod_ack,
)

PHOTOS_DIR = ROOT / "data" / "arena-cards" / "photos"
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

HIDE_IDS: tuple[int, ...] = (13, 14)
SHOW_IDS: tuple[int, ...] = (12,)
#: Немигу ловим по названию/адресу: её id в выгрузке data/minsk-arenas-prod.csv нет.
HIDE_NAME_PATTERNS: tuple[str, ...] = ("%немиг%",)
HIDE_VENUE_TYPES: tuple[str, ...] = ("gym",)


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("Set DATABASE_URL_SYNC or DATABASE_URL")
    return normalize_db_url(raw)


async def _arenas_to_hide(session: AsyncSession) -> dict[int, str]:
    found: dict[int, str] = {}
    rows = await session.execute(
        text("SELECT id, name FROM arenas WHERE id = ANY(:ids) OR venue_type = ANY(:types)"),
        {"ids": list(HIDE_IDS), "types": list(HIDE_VENUE_TYPES)},
    )
    found.update({int(r[0]): str(r[1]) for r in rows.fetchall()})
    for pattern in HIDE_NAME_PATTERNS:
        rows = await session.execute(
            text("SELECT id, name FROM arenas WHERE name ILIKE :p OR address ILIKE :p"),
            {"p": pattern},
        )
        found.update({int(r[0]): str(r[1]) for r in rows.fetchall()})
    return found


async def _set_status(session: AsyncSession, arena_id: int, name: str, status: str, apply: bool) -> None:
    row = (
        await session.execute(
            text("SELECT status FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id}
        )
    ).fetchone()
    current = row[0] if row else None
    if current == status:
        print(f"  [same] arena_id={arena_id} {name!r} — уже {status}")
        return
    print(f"  [{'apply' if apply else 'dry-run'}] arena_id={arena_id} {name!r} — {current!r} -> {status}")
    if apply:
        await apply_admin_arena_profile_patch(session, arena_id, {"status": status})


async def _upload_photos(session: AsyncSession, apply: bool) -> None:
    if not PHOTOS_DIR.is_dir():
        return
    for folder in sorted(PHOTOS_DIR.glob("arena-*")):
        try:
            arena_id = int(folder.name.split("-", 1)[1])
        except ValueError:
            continue
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_EXTS)
        if not files:
            continue
        exists = (
            await session.execute(text("SELECT 1 FROM arenas WHERE id = :id"), {"id": arena_id})
        ).fetchone()
        if not exists:
            print(f"  [skip] photos {folder.name}: arena_id={arena_id} нет в БД")
            continue
        have = (
            await session.execute(
                text("SELECT COUNT(*) FROM media WHERE owner_type = :ot AND owner_id = :id"),
                {"ot": MEDIA_OWNER_ARENA, "id": arena_id},
            )
        ).scalar_one()
        if have:
            print(f"  [skip] photos arena_id={arena_id}: уже {have} кадр(ов)")
            continue
        for path in files:
            print(f"  [{'apply' if apply else 'dry-run'}] photo arena_id={arena_id} <- {path.name}")
            if apply:
                ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                await upload_arena_media_from_bytes(
                    session,
                    arena_id,
                    path.read_bytes(),
                    ctype,
                    license_key="user",
                    attribution="Предоставлено владельцем продукта",
                )


async def run(*, apply: bool, show: bool, i_know_this_is_prod: bool) -> None:
    url = _db_url()
    assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
    if i_know_this_is_prod:
        warn_prod_ack()
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    engine = create_async_engine(url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        hide_status = ARENA_PROFILE_STATUS_PUBLISHED if show else ARENA_PROFILE_STATUS_ARCHIVED
        print("Скрыть в каталоге:" if not show else "Вернуть в каталог:")
        for arena_id, name in sorted((await _arenas_to_hide(session)).items()):
            await _set_status(session, arena_id, name, hide_status, apply)
        if not show:
            print("Показать:")
            for arena_id in SHOW_IDS:
                row = (
                    await session.execute(text("SELECT name FROM arenas WHERE id = :id"), {"id": arena_id})
                ).fetchone()
                if row is None:
                    print(f"  [skip] arena_id={arena_id} нет в БД")
                    continue
                await _set_status(session, arena_id, row[0], ARENA_PROFILE_STATUS_PUBLISHED, apply)
            print("Фото:")
            await _upload_photos(session, apply)
        if apply:
            await session.commit()
            print("\nГотово.")
        else:
            print("\nDry-run — ничего не записано. Добавь --apply.")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Записать в БД (по умолчанию dry-run).")
    parser.add_argument("--show", action="store_true", help="Вернуть скрытые площадки в каталог.")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, show=args.show, i_know_this_is_prod=args.i_know_this_is_prod))


if __name__ == "__main__":
    main()
