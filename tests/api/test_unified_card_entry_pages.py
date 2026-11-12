"""TASK-402: catalog.html и book.html несут флаг единой карточки, пока он включён (без БД)."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request

from src.api.asset_stamp import stamp_html

WEBAPP = Path(__file__).resolve().parents[2] / "static" / "webapp"


def _request(query: str = "trainer_id=7") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/webapp/catalog", "query_string": query.encode(), "headers": []})


def _pages():
    from src.api.app import webapp_book_page, webapp_catalog_page

    return [("catalog.html", lambda: webapp_catalog_page(_request())), ("book.html", webapp_book_page)]


@pytest.mark.parametrize("name", ["catalog.html", "book.html"])
def test_page_unchanged_when_flag_off(monkeypatch, name) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "false")
    body = dict(_pages())[name]().body.decode()
    assert body == stamp_html((WEBAPP / name).read_text(encoding="utf-8"))
    assert "__UNIFIED_TRAINER_CARD__" not in body


@pytest.mark.parametrize("name", ["catalog.html", "book.html"])
def test_page_carries_flag_before_shim_when_on(monkeypatch, name) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    body = dict(_pages())[name]().body.decode()
    assert body.count("__UNIFIED_TRAINER_CARD__") == 1
    # шим читает флаг при загрузке: скрипт флага обязан стоять раньше booking-deeplink.js
    assert body.index("__UNIFIED_TRAINER_CARD__=true") < body.index("booking-deeplink.js")
    assert "window.__UNIFIED_TRAINER_CARD__=true;" in body


def test_shim_source_keeps_exclusions() -> None:
    src = (WEBAPP / "booking-deeplink.js").read_text(encoding="utf-8")
    for needle in ("collective", "group_id", "request_id", "__UNIFIED_TRAINER_CARD__"):
        assert needle in src
