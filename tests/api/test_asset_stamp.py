"""Метка ``?v=`` у js/css Mini App ставит сервер: одна на все страницы, руками в html не двигаем."""

from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import asset_stamp as mod
from src.api.app import app

_V = re.compile(r"\.(?:js|css)\?v=(\d+)")


@pytest.fixture(autouse=True)
def _fresh_stamp():
    mod.reset_asset_stamp_for_tests()
    yield
    mod.reset_asset_stamp_for_tests()


def test_stamp_is_digits_and_follows_static_content(monkeypatch, tmp_path) -> None:
    (tmp_path / "a.js").write_text("one", encoding="utf-8")
    monkeypatch.setattr(mod, "_ROOTS", (tmp_path,))
    first = mod.asset_stamp()
    assert first.isdigit() and 6 <= len(first) <= 16
    mod.reset_asset_stamp_for_tests()
    assert mod.asset_stamp() == first, "те же файлы — та же метка (у всех реплик одного деплоя)"
    (tmp_path / "a.js").write_text("two", encoding="utf-8")
    mod.reset_asset_stamp_for_tests()
    assert mod.asset_stamp() != first, "правка файла — новая метка, руками её двигать не надо"
    (tmp_path / "notes.txt").write_text("not served as asset", encoding="utf-8")
    mod.reset_asset_stamp_for_tests()
    second = mod.asset_stamp()
    (tmp_path / "notes.txt").write_text("changed", encoding="utf-8")
    mod.reset_asset_stamp_for_tests()
    assert mod.asset_stamp() == second, "посторонние файлы метку не двигают"


def test_stamp_html_touches_only_js_and_css_versions() -> None:
    stamp = mod.asset_stamp()
    html = (
        '<script src="a.js?v=202611043"></script>'
        '<link rel="stylesheet" href="b.css?v=1" />'
        '<link href="/static/fonts/x.woff2?v=__FONT_V__" />'
        '<a href="/catalog?v=7">x</a>'
    )
    out = mod.stamp_html(html)
    assert f'a.js?v={stamp}' in out and f'b.css?v={stamp}' in out
    assert "?v=__FONT_V__" in out and "/catalog?v=7" in out


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/webapp/client-home", "/webapp/client-matches", "/webapp/book", "/webapp/client-register"])
async def test_served_pages_carry_the_same_server_stamp(path: str) -> None:
    stamp = mod.asset_stamp()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(path)
    assert resp.status_code == 200
    versions = set(_V.findall(resp.text))
    assert versions == {stamp}, (path, versions)
    assert resp.headers["cache-control"].startswith("no-")
