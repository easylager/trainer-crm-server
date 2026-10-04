"""Load parser source bytes from a local fixture_dir (tests) or HTTP (worker)."""
from __future__ import annotations

import json
import ssl
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import aiohttp

from src.ingestion.types import ParserJob

_USER_AGENT = "trainer-crm-ice-ingest/1.0"

# Прокси для заданий с requires_by_egress (сайты, которые отдают 403 небелорусским IP).
# Планировщик выставляет его на время одного задания, а все загрузчики ниже читают его
# сами — параметр не нужно протаскивать через два десятка парсеров.
_EGRESS_PROXY: ContextVar[str | None] = ContextVar("ice_egress_proxy", default=None)


@contextmanager
def egress_proxy(url: str | None) -> Iterator[None]:
    token = _EGRESS_PROXY.set(url or None)
    try:
        yield
    finally:
        _EGRESS_PROXY.reset(token)


def current_egress_proxy() -> str | None:
    return _EGRESS_PROXY.get()


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """Доверие — по системному хранилищу ОС, если есть truststore.

    Встроенный в Python набор корней не знает корпоративных/антивирусных/VPN-сертификатов,
    которые ОС и браузер уже считают своими: на Mac это даёт «self-signed certificate in
    certificate chain» там, где Safari открывает сайт. truststore берёт то же хранилище,
    что и браузер. Нет пакета — обычный контекст (учитывает SSL_CERT_FILE).
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return ssl.create_default_context()


def client_session(timeout_s: float) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout_s),
        connector=aiohttp.TCPConnector(ssl=ssl_context()),
    )


async def fetch_http_bytes(url: str, *, headers: dict[str, str] | None = None, timeout_s: float = 20) -> bytes:
    request_headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    async with client_session(timeout_s) as session:
        async with session.get(url, headers=request_headers, proxy=current_egress_proxy()) as response:
            response.raise_for_status()
            return await response.read()


async def fetch_http_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    request_headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    async with client_session(20) as session:
        async with session.get(url, headers=request_headers, proxy=current_egress_proxy()) as response:
            response.raise_for_status()
            return await response.text()


async def fetch_http_text_optional(url: str, *, headers: dict[str, str] | None = None) -> str | None:
    """GET body or None on HTTP/network failure (ledlife price fallbacks)."""
    request_headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    try:
        async with client_session(20) as session:
            async with session.get(url, headers=request_headers, proxy=current_egress_proxy()) as response:
                if response.status >= 400:
                    return None
                return await response.text()
    except (aiohttp.ClientError, TimeoutError):
        return None


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
