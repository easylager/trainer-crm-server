"""Load parser source bytes from a local fixture_dir (tests) or HTTP (worker)."""
from __future__ import annotations

import ipaddress
import json
import socket
import ssl
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import aiohttp

from src.ingestion.types import ParserJob

_USER_AGENT = "trainer-crm-ice-ingest/1.0"

MAX_HTTP_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_HTTP_REDIRECTS = 5

# Прокси для заданий с requires_by_egress (сайты, которые отдают 403 небелорусским IP).
# Планировщик выставляет его на время одного задания, а все загрузчики ниже читают его
# сами — параметр не нужно протаскивать через два десятка парсеров.
_EGRESS_PROXY: ContextVar[str | None] = ContextVar("ice_egress_proxy", default=None)


class FetchRejectedError(ValueError):
    """URL or response rejected by ingestion fetch policy (SSRF, size, redirects)."""


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


def _reject_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise FetchRejectedError(f"fetch blocked for disallowed address {ip}")


def assert_fetch_url_allowed(url: str) -> None:
    """Reject private/loopback/link-local targets (SSRF guard). Checks resolved IPs for hostnames."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchRejectedError(f"fetch blocked: unsupported scheme {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise FetchRejectedError("fetch blocked: missing hostname")
    try:
        _reject_disallowed_ip(ipaddress.ip_address(host))
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchRejectedError(f"fetch blocked: cannot resolve {host!r}") from exc
    if not infos:
        raise FetchRejectedError(f"fetch blocked: no addresses for {host!r}")
    for info in infos:
        _reject_disallowed_ip(ipaddress.ip_address(info[4][0]))


async def _read_body_limited(response: aiohttp.ClientResponse, limit: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            length = int(content_length)
        except ValueError:
            length = None
        if length is not None and length > limit:
            raise FetchRejectedError(f"response Content-Length {content_length} exceeds {limit} bytes")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise FetchRejectedError(f"response body exceeds {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def _get_bytes_follow_redirects(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str],
    proxy: str | None,
    limit: int,
) -> bytes:
    current = url
    for _ in range(MAX_HTTP_REDIRECTS + 1):
        assert_fetch_url_allowed(current)
        async with session.get(current, headers=headers, proxy=proxy, allow_redirects=False) as response:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise FetchRejectedError(f"redirect without Location from {current}")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            return await _read_body_limited(response, limit)
    raise FetchRejectedError(f"too many redirects (>{MAX_HTTP_REDIRECTS})")


async def fetch_http_bytes(url: str, *, headers: dict[str, str] | None = None, timeout_s: float = 20) -> bytes:
    request_headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    async with client_session(timeout_s) as session:
        return await _get_bytes_follow_redirects(
            session,
            url,
            headers=request_headers,
            proxy=current_egress_proxy(),
            limit=MAX_HTTP_RESPONSE_BYTES,
        )


async def fetch_http_text(url: str, *, headers: dict[str, str] | None = None) -> str:
    raw = await fetch_http_bytes(url, headers=headers, timeout_s=20)
    return raw.decode("utf-8", errors="replace")


async def fetch_http_text_optional(url: str, *, headers: dict[str, str] | None = None) -> str | None:
    """GET body or None on HTTP/network failure (ledlife price fallbacks)."""
    try:
        return await fetch_http_text(url, headers=headers)
    except (aiohttp.ClientError, TimeoutError, FetchRejectedError):
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
