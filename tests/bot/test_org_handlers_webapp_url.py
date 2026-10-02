"""TASK-141: fresh claim opens straight into org-profile, not org-home.

Regression: the claim-success button was labeled "Заполнить профиль" but the URL it opened
was hardcoded to org-home regardless — the director had to tap through Home first to reach
the one screen this flow exists to get them to.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.bot.handlers.org_handlers import _org_webapp_markup, org_cabinet_webapp_url


def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.org_webapp_base_url = "https://org.example.com"
    monkeypatch.setattr("src.bot.handlers.org_handlers.Settings", lambda: settings)


def test_default_path_is_org_home(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    assert org_cabinet_webapp_url() == "https://org.example.com/webapp/org-home"


def test_explicit_path_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    assert org_cabinet_webapp_url(path="org-profile") == "https://org.example.com/webapp/org-profile"


def test_fresh_claim_markup_opens_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    markup = _org_webapp_markup(fill_profile=True)
    assert markup is not None
    url = markup.inline_keyboard[0][0].web_app.url
    assert url == "https://org.example.com/webapp/org-profile"


def test_return_visit_markup_opens_home(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    markup = _org_webapp_markup(fill_profile=False)
    assert markup is not None
    url = markup.inline_keyboard[0][0].web_app.url
    assert url == "https://org.example.com/webapp/org-home"
