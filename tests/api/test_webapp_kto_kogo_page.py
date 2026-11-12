"""TASK-299: страница «Кто кого» отдаётся и тянет свои ассеты с версией."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from src.api.app import app


def test_kto_kogo_page_served_with_versioned_assets() -> None:
    client = TestClient(app)
    r = client.get("/webapp/kto-kogo")
    assert r.status_code == 200
    for asset in ("kto-kogo.css", "kto-kogo-model.js", "kto-kogo.js", "kto-kogo-matches.js"):
        assert re.search(rf"/static/webapp/{re.escape(asset)}\?v=\d+", r.text), asset
        assert client.get(f"/static/webapp/{asset}").status_code == 200


def test_home_page_loads_the_kto_kogo_row() -> None:
    """TASK-303: «Кто кого» — карточка слота «сейчас» в hub-home.js, без отдельных файлов строки."""
    html = TestClient(app).get("/webapp/client-home").text
    assert "hub-home.js?v=" in html
    hub = TestClient(app).get("/webapp/hub-home.js")
    assert hub.status_code == 200
    assert "/api/webapp/client/hockey/matches/" in hub.text
    assert "kto-kogo?reveal=" in hub.text


def test_kto_kogo_page_uses_self_hosted_fonts() -> None:
    """TASK-388: шрифты свои, как на главной; Google Fonts держали load ~0,9 с. Preload совпадает с CSS."""
    from src.application.style_b import PUBLIC_FONTS_ASSET_VERSION

    html = TestClient(app).get("/webapp/kto-kogo").text
    assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html
    assert "__FONT_V__" not in html
    assert f"dela-gothic-one-cyr-lat.woff2?v={PUBLIC_FONTS_ASSET_VERSION}" in html
    assert f"golos-text-cyr-lat.woff2?v={PUBLIC_FONTS_ASSET_VERSION}" in html
    assert re.search(r"/static/shared/glide-public-fonts\.css\?v=\d+", html)
