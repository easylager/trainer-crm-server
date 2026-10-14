"""Пересжать крупные варианты фото катков, которые загрузились без пересжатия.

До исправления ``_resize_image`` JPEG не больше 1600 px сохранялся как прислали:
экспорт камеры или редактора на ~95% уходил в ``_hero.jpg`` весом до 1,5 МБ,
а телефоны с экраном 3x грузят именно его. Скрипт пересжимает такие файлы тем
же кодом, что и загрузка, и кладёт по тому же ключу (кэш immutable: у кого
старая копия — видят ту же картинку).

По умолчанию dry-run: читает базу и хранилище, печатает план, ничего не пишет.
``--apply`` сначала копирует исходник в ``backup/arena-hero-originals/<ключ>``,
потом перезаписывает. Файл берётся, только если стал легче хотя бы на 10%.
Облачная база — только с ``--i-know-this-is-prod``. Повторный запуск ничего
не находит: пересжатый файл второй раз легче не станет.

  DATABASE_URL=<public> S3_*=<prod> PYTHONPATH=. \\
    python scripts/recompress_arena_heroes.py --i-know-this-is-prod
  … --apply --i-know-this-is-prod
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from src.shared.ops_db_guard import (  # noqa: E402
    ProdDatabaseError,
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    warn_prod_ack,
)

BACKUP_PREFIX = "backup/arena-hero-originals/"
MIN_SAVING = 0.10

_HERO_KEYS_SQL = text(
    """
    SELECT id, variants FROM media
    WHERE owner_type = 'arena' AND status = 'published'
    ORDER BY id
    """
)


@dataclass(frozen=True)
class Plan:
    media_id: int
    key: str
    old_size: int
    new_body: bytes


def recompress(body: bytes) -> bytes:
    from src.infrastructure.s3 import PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY, _resize_image

    return _resize_image(body, "image/jpeg", PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY) or body


def plan_one(media_id: int, key: str, body: bytes) -> Plan | None:
    new_body = recompress(body)
    if len(new_body) > len(body) * (1 - MIN_SAVING):
        return None
    return Plan(media_id=media_id, key=key, old_size=len(body), new_body=new_body)


async def hero_keys(database_url: str) -> list[tuple[int, str]]:
    engine = create_async_engine(async_database_url(database_url))
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            rows = (await conn.execute(_HERO_KEYS_SQL)).all()
    finally:
        await engine.dispose()
    out: list[tuple[int, str]] = []
    for media_id, variants in rows:
        data = variants if isinstance(variants, dict) else json.loads(variants or "{}")
        key = str(data.get("hero") or "")
        if key.startswith("arenas/"):
            out.append((int(media_id), key))
    return out


def run(*, apply: bool, allow_prod: bool) -> int:
    from src.infrastructure.s3 import PHOTO_CACHE_CONTROL, _get_client
    from src.shared.config import Settings

    url = os.environ.get("DATABASE_URL") or ""
    if not url:
        print("ОШИБКА: нет DATABASE_URL", file=sys.stderr)
        return 2
    try:
        assert_database_url(url, apply=False, allow_prod=allow_prod)
    except ProdDatabaseError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    if allow_prod:
        warn_prod_ack()
    bucket = Settings().s3_bucket
    client = _get_client()
    keys = asyncio.run(hero_keys(url))
    plans: list[Plan] = []
    for media_id, key in keys:
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        plan = plan_one(media_id, key, body)
        if plan:
            plans.append(plan)
            print(f"{media_id:5d} {key}  {plan.old_size // 1024} KB -> {len(plan.new_body) // 1024} KB")
    old = sum(p.old_size for p in plans)
    new = sum(len(p.new_body) for p in plans)
    print(f"Проверено {len(keys)}, к пересжатию {len(plans)}: {old // 1024} KB -> {new // 1024} KB")
    if not apply:
        print("Dry-run: ничего не записано.")
        return 0
    for plan in plans:
        client.copy_object(
            Bucket=bucket,
            Key=BACKUP_PREFIX + plan.key,
            CopySource={"Bucket": bucket, "Key": plan.key},
        )
        client.put_object(
            Bucket=bucket,
            Key=plan.key,
            Body=plan.new_body,
            ContentType="image/jpeg",
            CacheControl=PHOTO_CACHE_CONTROL,
        )
        print(f"записано {plan.key} (исходник: {BACKUP_PREFIX}{plan.key})")
    print("Готово.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Пересжать тяжёлые _hero.jpg катков.")
    parser.add_argument("--apply", action="store_true", help="Записать в хранилище (по умолчанию dry-run).")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args(argv)
    return run(apply=args.apply, allow_prod=bool(args.i_know_this_is_prod))


if __name__ == "__main__":
    raise SystemExit(main())
