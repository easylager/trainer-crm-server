"""TASK-188: SSRF guard and response size limits on ingestion HTTP fetch."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.ingestion.source_io import (
    FetchRejectedError,
    MAX_HTTP_RESPONSE_BYTES,
    _get_bytes_follow_redirects,
    _read_body_limited,
    assert_fetch_url_allowed,
    fetch_http_bytes,
)


def test_assert_fetch_url_allowed_rejects_loopback_and_private() -> None:
    with pytest.raises(FetchRejectedError):
        assert_fetch_url_allowed("http://127.0.0.1/")
    with pytest.raises(FetchRejectedError):
        assert_fetch_url_allowed("http://10.0.0.1/")


@pytest.mark.asyncio
async def test_read_body_limited_rejects_oversized_stream() -> None:
    chunk = b"x" * (MAX_HTTP_RESPONSE_BYTES // 2 + 1)

    async def _iter_chunked(_size: int):
        yield chunk
        yield chunk

    response = MagicMock()
    response.headers = {}
    response.content.iter_chunked = _iter_chunked

    with pytest.raises(FetchRejectedError, match="exceeds"):
        await _read_body_limited(response, MAX_HTTP_RESPONSE_BYTES)


@pytest.mark.asyncio
async def test_read_body_limited_rejects_content_length() -> None:
    class _Response:
        headers = {"Content-Length": str(MAX_HTTP_RESPONSE_BYTES + 1)}

        class _Content:
            @staticmethod
            async def iter_chunked(_size: int):
                if False:
                    yield b""  # pragma: no cover

        content = _Content()

    with pytest.raises(FetchRejectedError, match="Content-Length"):
        await _read_body_limited(_Response(), MAX_HTTP_RESPONSE_BYTES)


@pytest.mark.asyncio
async def test_fetch_rejects_redirect_to_private_host() -> None:
    class _RedirectResponse:
        status = 302
        headers = {"Location": "http://10.0.0.1/secret"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self) -> None:
            return None

    session = MagicMock()

    def _get(url, **kwargs):
        assert kwargs.get("allow_redirects") is False
        return _RedirectResponse()

    session.get = _get

    with pytest.raises(FetchRejectedError):
        await _get_bytes_follow_redirects(
            session,
            "https://example.com/go",
            headers={"User-Agent": "test"},
            proxy=None,
            limit=1024,
        )


@pytest.mark.asyncio
async def test_fetch_accepts_small_public_response(monkeypatch) -> None:
    """Size/redirect logic on a mocked 200 — SSRF check skipped (target is not fetched)."""
    body = b"hello"

    class _FakeResponse:
        status = 200
        headers = {"Content-Length": str(len(body))}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self) -> None:
            return None

        async def read(self) -> bytes:
            return body

        @property
        def content(self):
            return self

        async def iter_chunked(self, _size: int):
            yield body

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, url, **kwargs):
            assert kwargs.get("allow_redirects") is False
            return _FakeResponse()

    monkeypatch.setattr("src.ingestion.source_io.client_session", lambda _timeout: _FakeSession())
    monkeypatch.setattr("src.ingestion.source_io.assert_fetch_url_allowed", lambda _url: None)
    assert await fetch_http_bytes("https://example.test/file") == body


def _fake_session_factory(body: bytes, charset: str | None):
    class _FakeResponse:
        status = 200
        headers = {"Content-Length": str(len(body))}

        def __init__(self) -> None:
            self.charset = charset

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def raise_for_status(self) -> None:
            return None

        @property
        def content(self):
            return self

        async def iter_chunked(self, _size: int):
            yield body

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, url, **kwargs):
            return _FakeResponse()

    return lambda _timeout: _FakeSession()


@pytest.mark.asyncio
async def test_fetch_http_text_honours_content_type_charset(monkeypatch) -> None:
    """Regression (batch review of TASK-188): windows-1251 pages must not be decoded as UTF-8."""
    from src.ingestion.source_io import fetch_http_text

    text = "Массовое катание 29 декабря"
    monkeypatch.setattr(
        "src.ingestion.source_io.client_session",
        _fake_session_factory(text.encode("cp1251"), "windows-1251"),
    )
    monkeypatch.setattr("src.ingestion.source_io.assert_fetch_url_allowed", lambda _url: None)
    assert await fetch_http_text("https://example.test/page") == text


@pytest.mark.asyncio
async def test_fetch_http_text_defaults_to_utf8_without_charset(monkeypatch) -> None:
    from src.ingestion.source_io import fetch_http_text

    text = "Лёд"
    monkeypatch.setattr(
        "src.ingestion.source_io.client_session", _fake_session_factory(text.encode("utf-8"), None)
    )
    monkeypatch.setattr("src.ingestion.source_io.assert_fetch_url_allowed", lambda _url: None)
    assert await fetch_http_text("https://example.test/page") == text


@pytest.mark.asyncio
async def test_ssrf_dns_check_runs_off_the_event_loop(monkeypatch) -> None:
    """Regression (batch review of TASK-188): blocking getaddrinfo must not run on the loop thread."""
    import threading

    seen: list[str] = []

    def _check(_url: str) -> None:
        seen.append(threading.current_thread().name)

    monkeypatch.setattr("src.ingestion.source_io.client_session", _fake_session_factory(b"ok", None))
    monkeypatch.setattr("src.ingestion.source_io.assert_fetch_url_allowed", _check)
    assert await fetch_http_bytes("https://example.test/file") == b"ok"
    assert seen and seen[0] != threading.current_thread().name
