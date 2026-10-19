"""Скачать логотипы команд из окна календаря hcdinamo.by в static/webapp/hockey-logos.

Повторный запуск не перекачивает уже лежащие PNG. В продукте на hcdinamo.by не ссылаемся.

Usage:
  PYTHONPATH=. python scripts/fetch_hockey_logos.py
"""

from __future__ import annotations

import asyncio
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.hockey_matches import default_fetch, match_url
from src.application.hockey_teams import logo_path, slug_for
from src.ingestion.hockey_sources import (
    HCDINAMO_BASE,
    HCDINAMO_CALENDAR_URL,
    parse_hcdinamo_calendar,
    parse_hcdinamo_logo_index,
)
from src.ingestion.source_io import fetch_http_bytes

_UA = {"User-Agent": "Mozilla/5.0 (compatible; GlideBot/1.0)"}


def _absolute(src: str) -> str:
    if src.startswith("http://") or src.startswith("https://"):
        return src
    if src.startswith("/"):
        return f"{HCDINAMO_BASE}{src}"
    return f"{HCDINAMO_BASE}/{src}"


_RESIZED = re.compile(r"/upload/resize_cache/(iblock/.+?)/\d+_\d+_\d+/([^/]+)$")


def original_url(url: str) -> str:
    """У Битрикса ``/upload/resize_cache/iblock/<x>/59_59_1/<f>`` — уменьшенная копия ``/upload/iblock/<x>/<f>``.

    Уменьшенная 59×59 размывается на экранах с плотностью ×3; оригинал — 200×200.
    """
    return _RESIZED.sub(r"/upload/\1/\2", url)


async def _download(url: str) -> bytes:
    original = original_url(url)
    if original != url:
        try:
            return await fetch_http_bytes(original, headers=_UA)
        except Exception:
            print(f"original failed, using resized: {original}")
    return await fetch_http_bytes(url, headers=_UA)


def _write_png(dest: Path, data: bytes) -> None:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGBA").save(dest, "PNG")


async def collect_logo_srcs() -> dict[str, str]:
    """Имя команды → абсолютный URL. Сначала календарь, затем страницы матчей окна."""
    calendar = await default_fetch(HCDINAMO_CALENDAR_URL)
    found = {name: _absolute(src) for name, src in parse_hcdinamo_logo_index(calendar).items()}
    for source_match_id in parse_hcdinamo_calendar(calendar):
        page = await default_fetch(match_url(source_match_id))
        # На странице матча логотип у td.club_name l/r крупнее, чем в ленте календаря.
        for name, src in parse_hcdinamo_logo_index(page).items():
            found[name] = _absolute(src)
    return found


async def main(*, force: bool = False) -> None:
    found = await collect_logo_srcs()
    if not found:
        raise SystemExit("hcdinamo: в окне календаря нет логотипов")
    saved = skipped = 0
    for name in sorted(found):
        dest = logo_path(slug_for(name))
        if not force and dest.is_file() and dest.stat().st_size > 0:
            skipped += 1
            print(f"skip {name} → {dest.name}")
            continue
        _write_png(dest, await _download(found[name]))
        saved += 1
        print(f"save {name} → {dest.name}")
    print(f"done saved={saved} skipped={skipped} teams={len(found)}")


if __name__ == "__main__":
    asyncio.run(main(force="--force" in sys.argv))
