"""IndexNow для glideclub.by: сообщаем поисковикам (Bing, Яндекс и др.), что страница изменилась.

Флаг ``INDEXNOW_ENABLED`` (по умолчанию выключен) и ключ ``INDEXNOW_KEY`` (32 hex).
Без обоих всё здесь — no-op: в сеть ничего не уходит, в базу тоже.

* ``submit_urls`` — POST на api.indexnow.org пачками до 10000, таймаут 10 с, никогда не бросает.
* ``notify_arena_changed`` — вызывается публикатором сеансов, когда набор сеансов арены
  действительно изменился; ищет URL арены и города по тем же правилам видимости, что
  sitemap, и отправляет их фоновой задачей (fire-and-forget).
* Дедуп: один URL не чаще раза в час. Кэш в памяти процесса: сбрасывается при
  рестарте и не общий между воркерами (Redis для такого в репозитории не используется).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import city_slug
from src.application.place_links import place_page_url
from src.shared.config import Settings
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

logger = logging.getLogger(__name__)

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH_SIZE = 10_000
TIMEOUT_SECONDS = 10.0
DEDUP_TTL_SECONDS = 3600.0
# Публикатор вызывает нас до коммита транзакции тика: небольшая пауза, чтобы краулер,
# пришедший по пингу, увидел уже закоммиченные сеансы.
NOTIFY_DELAY_SECONDS = 30.0
_KEY_RE = re.compile(r"^[0-9a-f]{32}$")

# Видимость места в sitemap: общий предикат + опубликованный профиль со slug.
# Единственный источник — им же собран sitemap в public_place_page.
SITEMAP_PLACE_WHERE_SQL = f"{PUBLIC_ARENA_VISIBLE_SQL} AND p.status = 'published' AND p.slug IS NOT NULL"

_PLACES_SQL = f"""
    SELECT c.name AS city_name, p.slug
    FROM arenas a
    JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE {SITEMAP_PLACE_WHERE_SQL}
    {{extra}}
    ORDER BY c.sort_order, c.id, a.id
"""

_recent: dict[str, float] = {}
_background: set[asyncio.Task[Any]] = set()


def _base() -> str:
    # Та же формула, что _base() в routes/public_place_page (импорт роутов в application дал бы цикл).
    return (Settings().webapp_base_url or "").strip().rstrip("/")


def active_key() -> str | None:
    """Ключ, если IndexNow включён и ключ валиден; иначе None."""
    settings = Settings()
    if not settings.indexnow_enabled:
        return None
    key = (settings.indexnow_key or "").strip().lower()
    if not _KEY_RE.match(key):
        return None
    return key


def build_payload(urls: Sequence[str], key: str, base: str) -> dict[str, Any]:
    host = urlparse(base).netloc
    return {"host": host, "key": key, "keyLocation": f"{base}/{key}.txt", "urlList": list(urls)}


def _reset_dedup() -> None:
    _recent.clear()


def _take_fresh(urls: Iterable[str], now: float) -> list[str]:
    for url, stamp in list(_recent.items()):
        if now - stamp >= DEDUP_TTL_SECONDS:
            del _recent[url]
    fresh: list[str] = []
    for url in dict.fromkeys(urls):
        if url not in _recent:
            _recent[url] = now
            fresh.append(url)
    return fresh


async def submit_urls(urls: Sequence[str], *, client: httpx.AsyncClient | None = None, dedup: bool = True) -> int:
    """Отправить URL в IndexNow. Возвращает число принятых URL. Не бросает."""
    try:
        key = active_key()
        if key is None or not urls:
            return 0
        base = _base()
        pending = _take_fresh(urls, time.monotonic()) if dedup else list(dict.fromkeys(urls))
        if not pending:
            return 0
        own = client is None
        http = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        accepted = 0
        try:
            for start in range(0, len(pending), BATCH_SIZE):
                batch = pending[start : start + BATCH_SIZE]
                ok = False
                try:
                    resp = await http.post(
                        INDEXNOW_ENDPOINT,
                        json=build_payload(batch, key, base),
                        headers={"Content-Type": "application/json; charset=utf-8"},
                        timeout=TIMEOUT_SECONDS,
                    )
                    ok = resp.status_code in (200, 202)
                    if not ok:
                        logger.warning("indexnow rejected batch of %d urls: HTTP %s", len(batch), resp.status_code)
                except Exception:  # noqa: BLE001 — сеть не должна ломать вызывающего
                    logger.exception("indexnow request failed for batch of %d urls", len(batch))
                if ok:
                    accepted += len(batch)
                elif dedup:
                    for url in batch:  # не помечаем неотправленное: можно повторить позже
                        _recent.pop(url, None)
        finally:
            if own:
                await http.aclose()
        return accepted
    except Exception:  # noqa: BLE001
        logger.exception("indexnow submit failed")
        return 0


async def fetch_sitemap_urls(session: AsyncSession) -> list[str]:
    """Все URL, которые перечисляет sitemap.xml, в его порядке."""
    base = _base()
    rows = (await session.execute(text(_PLACES_SQL.format(extra="")), public_scope_params())).mappings().all()
    urls = [f"{base}/", f"{base}/trainers"]
    seen_cities: set[str] = set()
    for row in rows:
        city = str(row["city_name"])
        if city not in seen_cities:
            seen_cities.add(city)
            urls.append(f"{base}/c/{city_slug(city)}")
        urls.append(place_page_url(base_url=base, city_name=city, slug=str(row["slug"])))
    return urls


async def arena_page_urls(session: AsyncSession, arena_id: int) -> list[str]:
    """Страница арены и страница её города — только если арена попала бы в sitemap."""
    base = _base()
    sql = text(_PLACES_SQL.format(extra="AND a.id = :indexnow_arena_id"))
    params = {**public_scope_params(), "indexnow_arena_id": int(arena_id)}
    row = (await session.execute(sql, params)).mappings().first()
    if row is None:
        return []
    city = str(row["city_name"])
    return [f"{base}/c/{city_slug(city)}", place_page_url(base_url=base, city_name=city, slug=str(row["slug"]))]


async def _delayed_submit(urls: list[str], delay: float) -> None:
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        await submit_urls(urls)
    except Exception:  # noqa: BLE001
        logger.exception("indexnow background submit failed")


def fire_and_forget(urls: list[str], *, delay: float | None = None) -> None:
    delay = NOTIFY_DELAY_SECONDS if delay is None else delay
    if not urls:
        return
    try:
        task = asyncio.get_running_loop().create_task(_delayed_submit(urls, delay))
    except RuntimeError:
        return
    _background.add(task)
    task.add_done_callback(_background.discard)


async def notify_arena_changed(session: AsyncSession, arena_id: int) -> None:
    """Вызывать, когда контент страницы арены реально изменился. Не бросает, не блокирует."""
    if active_key() is None:
        return
    try:
        # Savepoint: сбой SELECT не должен отравить транзакцию тика парсеров.
        async with session.begin_nested():
            urls = await arena_page_urls(session, arena_id)
        fire_and_forget(urls)
    except Exception:  # noqa: BLE001
        logger.exception("indexnow notify failed arena_id=%s", arena_id)
