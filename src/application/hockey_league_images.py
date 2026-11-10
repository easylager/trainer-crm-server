"""Картинка лиги «Кто кого» (TASK-361): проверка, перекодирование, хранение.

Владелец лиги загружает картинку свободно, без премодерации, поэтому файл считаем недоверенным:
тип определяем по содержимому (а не по заголовку запроса), вес и размер ограничиваем, картинку
перекодируем в JPEG — вместе с EXIF и любыми вложениями уходят и «вредные» файлы, — а имя файла
выдаём сами. В хранилище кладём два кадра: основной (до 1200 px) и маленький для списка лиг.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.photo_cdn import public_photo_url
from src.infrastructure import s3

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAIN_SIDE = 1200
THUMB_SIDE = 320
# Файл в 5 МБ может нести «бомбу» — картинку, которая в памяти занимает гигабайты. Берём не больше 48 Мп.
MAX_PIXELS = 48_000_000
ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")
_THUMB_SUFFIX = "_thumb.jpg"

_MESSAGES = {
    "empty": "Файл пустой. Выбери фото ещё раз",
    "too_large": "Фото больше 5 МБ. Выбери поменьше",
    "not_image": "Не получилось открыть файл. Нужна картинка JPEG, PNG или WEBP",
    "unsupported": "Подходят только JPEG, PNG и WEBP",
    "too_big_size": "Картинка слишком большая по размеру. Выбери другую",
    "storage": "Не получилось сохранить фото. Попробуй ещё раз",
}
_STATUS = {"empty": 400, "too_large": 413, "not_image": 400, "unsupported": 415, "too_big_size": 413, "storage": 503}


class LeagueImageError(ValueError):
    """Картинку принять нельзя; ``code`` — причина, ``str`` — текст для человека, ``status`` — код ответа."""

    def __init__(self, code: str):
        super().__init__(_MESSAGES[code])
        self.code = code
        self.status = _STATUS[code]


def thumb_key(image_key: str) -> str:
    """Ключ маленького кадра рядом с основным: ``.../abc.jpg`` → ``.../abc_thumb.jpg``."""
    base = image_key[:-4] if image_key.endswith(".jpg") else image_key
    return base + _THUMB_SUFFIX


def _flatten(img):
    """Прозрачность заливаем белым, а не чёрным: у PNG-значков под альфой часто чёрный цвет."""
    from PIL import Image

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        base = Image.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base
    return img.convert("RGB")


def _jpeg(img, quality: int) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)  # без exif= и icc_profile=
    return out.getvalue()


def prepare_image(body: bytes) -> tuple[bytes, bytes]:
    """Загруженные байты → (основной кадр, маленький кадр), оба JPEG без метаданных. Иначе ``LeagueImageError``."""
    if not body:
        raise LeagueImageError("empty")
    if len(body) > MAX_UPLOAD_BYTES:
        raise LeagueImageError("too_large")
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(body)) as img:
            if img.format not in ALLOWED_FORMATS:
                raise LeagueImageError("unsupported" if img.format else "not_image")
            width, height = img.size
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise LeagueImageError("too_big_size")
            if img.format == "JPEG":
                img.draft("RGB", (MAIN_SIDE, MAIN_SIDE))  # JPEG распаковывается сразу уменьшенным: быстро и без гигабайтов
            img.load()
            main = _flatten(ImageOps.exif_transpose(img))
    except LeagueImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise LeagueImageError("too_big_size") from None
    except Exception:  # битый, обрезанный или не картинка: подробности человеку не нужны
        raise LeagueImageError("not_image") from None
    main.thumbnail((MAIN_SIDE, MAIN_SIDE), Image.Resampling.LANCZOS)
    small = main.copy()
    small.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    return _jpeg(main, 82), _jpeg(small, 80)


def _store(league_id: int, main: bytes, small: bytes) -> str:
    key = f"{s3.LEAGUE_PREFIX}{int(league_id)}/{uuid.uuid4().hex}.jpg"
    prefixes = (s3.LEAGUE_PREFIX,)
    s3.put_bytes(key, main, "image/jpeg", allowed_prefixes=prefixes)
    try:
        s3.put_bytes(thumb_key(key), small, "image/jpeg", allowed_prefixes=prefixes)
    except Exception:
        s3.delete_file(key, allowed_prefixes=prefixes)
        raise
    return key


async def store_league_image(league_id: int, body: bytes) -> str:
    """Проверить, перекодировать и положить в хранилище. Возвращает ключ основного кадра."""
    main, small = await asyncio.to_thread(prepare_image, body)
    try:
        return await asyncio.to_thread(_store, league_id, main, small)
    except Exception:
        logger.exception("league image storage failed league_id=%s", league_id)
        raise LeagueImageError("storage") from None


def _purge(key: str) -> None:
    from src.infrastructure.photo_bytes_cache import photo_bytes_cache

    prefixes = (s3.LEAGUE_PREFIX,)
    for one in (key, thumb_key(key)):
        s3.delete_file(one, allowed_prefixes=prefixes)
        photo_bytes_cache.discard(one)


async def release_image(session: AsyncSession, image_key: str | None) -> bool:
    """Убрать файлы картинки, если на неё не ссылается ни одна лига (продолжение лиги делит картинку с исходной).

    Вызывать после commit: файл, на который ещё ссылается строка, удалять нельзя. Сбой хранилища не ломает вызывающего.
    """
    if not image_key or s3.resolve_object_key_under_prefixes(image_key, (s3.LEAGUE_PREFIX,)) is None:
        return False
    used = (
        await session.execute(
            text("SELECT EXISTS (SELECT 1 FROM hockey_leagues WHERE image_key = :key)"), {"key": image_key}
        )
    ).scalar_one()
    if used:
        return False
    try:
        await asyncio.to_thread(_purge, image_key)
    except Exception:  # noqa: BLE001 — хвост в хранилище не должен ронять ответ
        logger.warning("league image not removed key=%s", image_key, exc_info=True)
        return False
    return True


def image_urls(image_key: str | None) -> tuple[str | None, str | None]:
    """Публичные адреса основного и маленького кадра; нет картинки — ``(None, None)``."""
    if not image_key:
        return None, None
    from src.shared.config import Settings

    base = Settings().photo_cdn_base_url  # type: ignore[call-arg]
    return public_photo_url(image_key, base), public_photo_url(thumb_key(image_key), base)


__all__ = [
    "LeagueImageError",
    "MAX_UPLOAD_BYTES",
    "image_urls",
    "prepare_image",
    "release_image",
    "store_league_image",
    "thumb_key",
]
