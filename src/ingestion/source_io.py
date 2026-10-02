"""Load parser source bytes from a local fixture_dir (tests) or HTTP (worker)."""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

import aiohttp

from src.ingestion.types import ParserJob

_USER_AGENT = "trainer-crm-ice-ingest/1.0"

# PDEC-004: HTTP proxy with a real BY exit IP, set by the scheduler only around jobs whose
# config carries requires_by_egress — every other arena keeps fetching directly.
_egress_proxy: ContextVar[str | None] = ContextVar("ice_ingest_egress_proxy", default=None)


@contextmanager
def egress_proxy(proxy_url: str | None) -> Iterator[None]:
    token = _egress_proxy.set(proxy_url or None)
    try:
        yield
    finally:
        _egress_proxy.reset(token)


def current_egress_proxy() -> str | None:
    return _egress_proxy.get()


async def fetch_http_bytes(url: str, *, headers: dict[str, str] | None = None, timeout_sec: float = 20) -> bytes:
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    request_headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=request_headers, proxy=current_egress_proxy()) as response:
            response.raise_for_status()
            return await response.read()


async def fetch_http_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    timeout = aiohttp.ClientTimeout(total=20)
    request_headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=request_headers, proxy=current_egress_proxy()) as response:
            response.raise_for_status()
            return await response.text()


async def fetch_http_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    return json.loads(await fetch_http_text(url, headers=headers))


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
