"""Load parser source bytes from a local fixture_dir (tests) or HTTP (worker)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiohttp

from src.ingestion.types import ParserJob

_USER_AGENT = "trainer-crm-ice-ingest/1.0"


async def fetch_http_text(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"User-Agent": _USER_AGENT}) as response:
            response.raise_for_status()
            return await response.text()


async def fetch_http_json(url: str) -> Any:
    return json.loads(await fetch_http_text(url))


async def load_source_text(job: ParserJob, *, filename: str, url_keys: tuple[str, ...] = ("url",)) -> str:
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        path = Path(str(fixture_dir)) / filename
        return path.read_text(encoding="utf-8")
    return await fetch_http_text(_first_url(job.config, url_keys))


async def load_source_json(job: ParserJob, *, filename: str, url_keys: tuple[str, ...] = ("url",)) -> Any:
    raw = await load_source_text(job, filename=filename, url_keys=url_keys)
    return json.loads(raw)


def _first_url(config: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = config.get(key)
        if value:
            return str(value)
    raise RuntimeError(f"job.config missing source URL ({', '.join(keys)})")
