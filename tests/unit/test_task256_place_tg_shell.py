"""TASK-256: bootstrap Telegram shell on public place pages."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_b_html_includes_place_tg_shell_bootstrap() -> None:
    html = (REPO / "static/share/b.html").read_text(encoding="utf-8")
    assert "place-tg-shell.js" in html
    assert "clientTabBar" not in html
    assert "__PLACE_SHARE_BAR__" in html
    assert "__PLACE_SHARE_SCRIPTS__" in html


def test_place_tg_shell_assets_routed() -> None:
    app_src = (REPO / "src/api/app.py").read_text(encoding="utf-8")
    assert '@app.get("/static/share/place-tg-shell.js")' in app_src
    assert '@app.get("/static/share/place-tg-shell.css")' in app_src


def test_theme_includes_place_hero_view_transition() -> None:
    theme = (REPO / "static/webapp/mini-app-client-theme.css").read_text(encoding="utf-8")
    assert ".b-hero__img[data-vt-hero]" in theme
    assert re.search(r"client-arena-hero", theme)
    assert re.search(
        r"::view-transition-old\(client-arena-hero\),\s*"
        r"::view-transition-new\(client-arena-hero\)\s*\{[^}]*object-fit:\s*cover",
        theme,
    )


def test_place_shell_hero_is_full_bleed() -> None:
    css = (REPO / "static/share/place-tg-shell.css").read_text(encoding="utf-8")
    assert "body.b.client-shell-body .b-hero" in css
    assert "border-radius: 0" in css


def test_place_tg_shell_applies_style_b_tg_dark() -> None:
    boot = (REPO / "static/share/place-tg-shell.js").read_text(encoding="utf-8")
    assert "tg-dark" in boot
    assert "colorScheme === 'dark'" in boot
    assert "telegram-web-app.js" in boot
    assert "if (!getTg())" in boot


def test_public_place_shell_skips_client_api_and_auth_overlay() -> None:
    shell = (REPO / "static/webapp/mini-app-client-shell.js").read_text(encoding="utf-8")
    chrome = (REPO / "static/webapp/mini-app-telegram-chrome.js").read_text(encoding="utf-8")
    assert "if (isPublicPlaceRoute()) return Promise.resolve();" in shell
    # На /p/ boot() выходит до загрузки клиентской сессии (а с ней — подписок и диплинков).
    boot_idx = shell.index("function boot()")
    pub_return = shell.index("if (isPublicPlaceRoute())", boot_idx)
    session = shell.index("loadClientSessionBeforeDeepLink()", boot_idx)
    assert pub_return < session
    assert "if (isPublicPlaceRoute()) return;" in chrome
    assert "function showRecoverableOverlay()" in chrome
