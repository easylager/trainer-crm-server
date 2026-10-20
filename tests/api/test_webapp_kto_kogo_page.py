"""TASK-299: страница «Кто кого» отдаётся и тянет свои ассеты с версией."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from src.api.app import app


def test_kto_kogo_page_served_with_versioned_assets() -> None:
    client = TestClient(app)
    r = client.get("/webapp/kto-kogo")
    assert r.status_code == 200
    for asset in ("kto-kogo.css", "kto-kogo-model.js", "kto-kogo.js"):
        assert re.search(rf"/static/webapp/{re.escape(asset)}\?v=\d+", r.text), asset
        assert client.get(f"/static/webapp/{asset}").status_code == 200


def test_home_page_loads_the_kto_kogo_row() -> None:
    """TASK-303: «Кто кого» — карточка слота «сейчас» в hub-home.js, без отдельных файлов строки."""
    html = TestClient(app).get("/webapp/client-home").text
    assert "hub-home.js?v=" in html
    assert "hub-kto-kogo.js" not in html
    hub = TestClient(app).get("/webapp/hub-home.js")
    assert hub.status_code == 200
    assert "/api/webapp/client/hockey/matches/" in hub.text
    assert "kto-kogo?reveal=" in hub.text
