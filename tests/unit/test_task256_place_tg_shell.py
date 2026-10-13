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


def test_place_tg_shell_applies_style_b_tg_dark() -> None:
    boot = (REPO / "static/share/place-tg-shell.js").read_text(encoding="utf-8")
    assert "tg-dark" in boot
    assert "colorScheme === 'dark'" in boot
    assert "telegram-web-app.js" in boot
    assert "if (!getTg())" in boot
