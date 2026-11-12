"""TASK-391: оболочка «Я» + «Записи» за флагом fast_tabs — по тем же адресам, без редиректа."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlencode

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.client_tabs_shell import SHELL_TABS, page_html
from src.application.client_ui_flags import fast_tabs_enabled
from src.shared.config import Settings, get_settings

_UID = 7_391_000_001
_PAGES = [("me", "/webapp/client-me"), ("bookings", "/webapp/client-bookings")]


def _init_data(user_id: int = _UID, token: str | None = None) -> str:
    token = token if token is not None else Settings().telegram_bot_token_client
    v = {
        "auth_date": str(int(time.time())),
        "query_id": "AAfasttabs",
        "user": json.dumps({"id": user_id, "first_name": "T"}, separators=(",", ":")),
    }
    dcs = "\n".join(f"{k}={v[k]}" for k in sorted(v))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    v["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(v)


@pytest.fixture
def flags_env(monkeypatch: pytest.MonkeyPatch):
    def apply(season: str | None = None, fast: str | None = None) -> None:
        for name, value in (("CLIENT_SEASON_UI_TELEGRAM_IDS", season), ("CLIENT_FAST_TABS_TELEGRAM_IDS", fast)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        monkeypatch.delenv("CLIENT_SEASON_UI_PERCENT", raising=False)
        monkeypatch.delenv("CLIENT_FAST_TABS_PERCENT", raising=False)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _get(path: str, init: str | None = None):
    url = path + (f"?init_data={quote(init, safe='')}" if init else "")
    with TestClient(app) as client:
        return client.get(url)


def test_fast_tabs_needs_season_ui_and_its_own_list() -> None:
    s = Settings(client_season_ui_telegram_ids=[1, 2], client_fast_tabs_telegram_ids=[2, 3])
    assert fast_tabs_enabled(2, s) is True
    assert fast_tabs_enabled(1, s) is False, "season_ui без fast_tabs"
    assert fast_tabs_enabled(3, s) is False, "fast_tabs без season_ui не действует"
    assert not any(fast_tabs_enabled(k, Settings(client_season_ui_percent=100)) for k in range(-200, 200))
    everyone = Settings(client_season_ui_percent=100, client_fast_tabs_percent=100)
    assert all(fast_tabs_enabled(k, everyone) for k in range(-200, 200))


@pytest.mark.parametrize("tab,path", _PAGES)
def test_flag_off_serves_master_page_byte_for_byte(flags_env, tab: str, path: str) -> None:
    flags_env(season=str(_UID))
    plain = _get(path)
    with_init = _get(path, _init_data())
    assert plain.status_code == with_init.status_code == 200
    assert with_init.text == plain.text == page_html(tab)
    assert "no-store" in with_init.headers["cache-control"]
    assert "data-ft-shell" not in with_init.text


@pytest.mark.parametrize("tab,path", _PAGES)
def test_flag_on_serves_shell_at_same_address(flags_env, tab: str, path: str) -> None:
    flags_env(season=str(_UID), fast=str(_UID))
    r = _get(path, _init_data())
    assert r.status_code == 200
    assert r.history == []
    html = r.text
    assert f'<html data-ft-shell="{tab}"' in html
    assert f'<div class="ft-tab" data-ft-tab="{tab}" data-ft-path="{SHELL_TABS[tab][0]}">' in html
    assert '<script defer src="client-tabs.js?v=' in html
    assert html.rstrip().endswith("</div>\n</body>\n</html>")
    # bfcache: no-cache без no-store, как у «Поиска».
    assert r.headers["cache-control"] == "private, no-cache, must-revalidate"
    # Остальная страница — та же, что без флага.
    master = page_html(tab)
    for part in (master.split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0],):
        assert part in html


@pytest.mark.parametrize("tab,path", _PAGES)
def test_no_valid_init_data_means_master_page(flags_env, tab: str, path: str) -> None:
    flags_env(season=str(_UID), fast=str(_UID))
    for init in (None, _init_data(token="1:wrong"), _init_data(user_id=_UID + 1)):
        r = _get(path, init)
        assert r.text == page_html(tab)
        assert "no-store" in r.headers["cache-control"]


def test_tab_fragment_is_the_page_without_scripts() -> None:
    with TestClient(app) as client:
        r = client.get("/webapp/client-tab/bookings.json?v=1")
        assert r.status_code == 200
        assert "immutable" in r.headers["cache-control"]
        frag = r.json()
        assert client.get("/webapp/client-tab/nope.json").status_code == 404
        assert "no-store" in client.get("/webapp/client-tab/me.json").headers["cache-control"]
    assert frag["tab"] == "bookings" and frag["path"] == "client-bookings"
    assert frag["title"] == "Записи"
    assert frag["bodyClass"] == "client-bookings-body ga-body"
    assert "<script" not in frag["html"]
    assert 'id="screenList"' in frag["html"] and 'id="modalCancel"' in frag["html"]
    css = [c.get("href", "<style>").split("?")[0] for c in frag["css"]]
    assert css[-1] == "<style>", "встроенный стиль страницы — на своём месте в каскаде"
    assert css.index("mini-app-client-bookings.css") < css.index("mini-app-client-shell.css")
    srcs = [s.get("src", "<code>").split("?")[0] for s in frag["scripts"]]
    assert srcs.count("<code>") == 4, "все встроенные скрипты страницы, по порядку"
    assert srcs.index("mini-app-client-home.js") > srcs.index("<code>")
    main = [s["code"] for s in frag["scripts"] if "code" in s and "loadBookings" in s["code"]]
    assert len(main) == 1 and "client-tabs:refresh" in main[0]


def test_me_fragment_lists_page_assets_in_order() -> None:
    with TestClient(app) as client:
        frag = client.get("/webapp/client-tab/me.json?v=1").json()
    srcs = [s["src"].split("?")[0].rsplit("/", 1)[-1] for s in frag["scripts"]]
    assert srcs[-2:] == ["client-me.js", "ga-touch.js"]
    assert srcs.index("client-sheet.js") < srcs.index("client-name-sheet.js") < srcs.index("client-me.js")
    assert [s for s in frag["scripts"] if s["src"].endswith("ga-press.js?v=" + s["src"].split("?v=")[-1])][0]["defer"]
    assert frag["bodyClass"] == "cm-body" and frag["title"] == "Я"
    assert 'id="meRoot"' in frag["html"]


def test_router_and_fragment_versions_follow_asset_stamp(flags_env) -> None:
    from src.api.asset_stamp import asset_stamp

    flags_env(season=str(_UID), fast=str(_UID))
    html = _get("/webapp/client-me", _init_data()).text
    assert f"client-tabs.js?v={asset_stamp()}" in html
    with TestClient(app) as client:
        js = client.get(f"/webapp/client-tabs.js?v={asset_stamp()}")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
    assert "ClientTabsModel" in js.text
