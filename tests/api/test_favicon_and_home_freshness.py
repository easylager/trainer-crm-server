"""Фавикон отвечает на HEAD (Яндекс), 120×120 в <head>, честный сигнал свежести на главной."""

from __future__ import annotations

import struct
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.catalog_home_page import home_freshness_text

_MINSK = ZoneInfo("Europe/Minsk")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/favicon.ico", "/favicon-120.png"])
async def test_favicon_get_and_head_200(path: str) -> None:
    async with _client() as client:
        head = await client.head(path)
        get = await client.get(path)
    assert head.status_code == 200
    assert head.headers["content-type"] == "image/png"
    assert get.status_code == 200
    assert get.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_favicon_120_is_120x120() -> None:
    async with _client() as client:
        body = (await client.get("/favicon-120.png")).content
    assert struct.unpack(">II", body[16:24]) == (120, 120)


@pytest.mark.asyncio
async def test_logos_head_200() -> None:
    async with _client() as client:
        resp = await client.head("/logos/01-icon/glide-icon-teal-square-512.png")
    assert resp.status_code == 200


def _utc(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=_MINSK).astimezone(timezone.utc)


def test_freshness_today_in_minsk_time() -> None:
    text = home_freshness_text(_utc(2026, 11, 3, 9, 5), _utc(2026, 11, 3, 13, 0))
    assert text == "Актуальное расписание массового катания · обновлено сегодня в 09:05"


def test_freshness_yesterday_not_today() -> None:
    text = home_freshness_text(_utc(2026, 11, 2, 23, 40), _utc(2026, 11, 3, 0, 30))
    assert text == "Актуальное расписание массового катания · обновлено вчера в 23:40"


def test_freshness_stale_or_missing_falls_back() -> None:
    fallback = "Актуальное расписание массового катания по всей Беларуси"
    assert home_freshness_text(None, _utc(2026, 11, 3, 13, 0)) == fallback
    assert home_freshness_text(_utc(2026, 10, 20, 9, 0), _utc(2026, 11, 3, 13, 0)) == fallback


@pytest.mark.asyncio
async def test_home_html_has_visible_freshness_and_icon_120(app_use_test_db) -> None:
    async with _client() as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert '<p class="b-hero__fresh">Актуальное расписание массового катания' in html
    assert 'sizes="120x120" href="/favicon-120.png"' in html
