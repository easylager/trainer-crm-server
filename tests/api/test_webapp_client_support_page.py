"""TASK-303: сообщество и поддержка переехали с главной в «Ещё»."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.api.app import app

_WEBAPP = Path(__file__).resolve().parents[2] / "static" / "webapp"


def test_support_page_is_served_with_the_form() -> None:
    page = TestClient(app).get("/webapp/client-support")
    assert page.status_code == 200
    assert 'id="supportForm"' in page.text
    assert "/api/webapp/support" in page.text
    assert "fonts.googleapis.com" not in page.text


def test_support_is_in_more_and_gone_from_home() -> None:
    shell = (_WEBAPP / "mini-app-client-shell.js").read_text(encoding="utf-8")
    icons = (_WEBAPP / "mini-app-more-icons.js").read_text(encoding="utf-8")
    home = (_WEBAPP / "client-home.html").read_text(encoding="utf-8")
    assert "path: 'client-support'" in shell
    assert "'client-support':" in icons
    assert "hubSupportForm" not in home
