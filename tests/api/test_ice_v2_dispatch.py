"""Фикс-пак B5: /webapp/ice диспатч value-aware — «Лёд» v2 только линзы расписания;
/webapp/service — экран «Сервис» под redesign_s4, иначе редирект в старый каталог."""

from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

import src.api.app as app_module
from src.api.app import app
from src.shared.config import get_settings
from tests.api.test_client_fast_tabs_shell import _init_data

_UID = 7_449_000_001


@pytest.fixture
def s4_env(monkeypatch: pytest.MonkeyPatch):
    def apply(on: bool) -> None:
        monkeypatch.setenv("CLIENT_REDESIGN_S4_TELEGRAM_IDS", str(_UID) if on else "0")
        monkeypatch.delenv("CLIENT_REDESIGN_S4_PERCENT", raising=False)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _get(path: str):
    with TestClient(app) as client:
        return client.get(path, follow_redirects=False)


def test_ice_v2_dispatch_is_value_aware(s4_env, tmp_path, monkeypatch) -> None:
    """intent=service больше не «параметр, который v2 понимает» — старый каталог."""
    v2 = tmp_path / "client-ice-v2.html"
    v2.write_text("<html><body>ICE-V2-MARK</body></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_ICE_V2_PATH", v2)
    s4_env(True)
    init = "init_data=" + quote(_init_data(_UID), safe="")
    for q in (
        "", "&city_id=1", "&intent=skate", "&intent=ohm", "&kind=figure",
        "&when=weekend", "&when=any", "&day=2026-11-28",
    ):
        body = _get(f"/webapp/ice?{init}{q}").text
        assert "ICE-V2-MARK" in body, q
    for q in (
        "&intent=service", "&venue=shop", "&kind=coach",
        "&when=today_evening", "&day=nonsense", "&seg=ohm",
    ):
        body = _get(f"/webapp/ice?{init}{q}").text
        assert "ICE-V2-MARK" not in body, q


def test_service_page_under_s4(s4_env, tmp_path, monkeypatch) -> None:
    svc = tmp_path / "client-service.html"
    svc.write_text("<html><body>SVC-MARK</body></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_SERVICE_V2_PATH", svc)
    s4_env(True)
    init = "init_data=" + quote(_init_data(_UID), safe="")
    body = _get(f"/webapp/service?{init}&tab=shop&city_id=1").text
    assert "SVC-MARK" in body


def test_service_page_falls_back_to_old_catalog(s4_env, tmp_path, monkeypatch) -> None:
    svc = tmp_path / "client-service.html"
    svc.write_text("<html><body>SVC-MARK</body></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_SERVICE_V2_PATH", svc)
    s4_env(False)
    r = _get("/webapp/service?tab=shop&city_id=1")
    assert r.status_code == 307
    assert r.headers["location"] == "/webapp/ice?city_id=1&venue=shop"
    r2 = _get("/webapp/service?intent=service")
    assert r2.headers["location"] == "/webapp/ice?intent=service"
    # Без init_data principal=None — тот же фолбэк.
    s4_env(True)
    r3 = _get("/webapp/service?tab=service")
    assert r3.status_code == 307
    assert r3.headers["location"] == "/webapp/ice?intent=service"
