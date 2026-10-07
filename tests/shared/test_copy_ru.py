"""TASK-209: один словарь подписей — Python (``t()``) и JS (``GlideCopy.t()``) не расходятся."""

from __future__ import annotations

import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from src.shared.copy_ru import COPY, t

_REPO_ROOT = Path(__file__).resolve().parents[2]
_JSON_PATH = _REPO_ROOT / "src" / "shared" / "copy_ru.json"
_JS_PATH = _REPO_ROOT / "static" / "webapp" / "glide-copy.js"

# AC-2: литералы палитры Glide не живут в шаблонах, только в токене.
_PALETTE_LITERALS = ("#0f8f8a", "#0d1b26", "#e1e8ec", "#f4f6f7")
_PALETTE_TEMPLATES = (
    "static/share/place.html",
    "static/share/catalog-home.html",
    "static/share/ice-city-day.html",
    "static/webapp/ice.html",
    "static/webapp/arena.html",
    "static/webapp/client-home.html",
    "static/webapp/catalog.html",
)

# AC-3: меню времени сайта и Mini App. Чужие «Выходные» (хаб тренера, теги досье) — не это меню.
_TIME_MENU_PATHS = (
    "static/webapp/ice-tab-model.js",
    "static/webapp/ice.html",
    "static/share/place.html",
    "static/share/catalog-home.html",
    "static/share/ice-city-day.html",
    "src/application/ice_time_windows.py",
    "src/application/selection_page.py",
    "src/application/place_page.py",
    "src/application/ice_city_day.py",
    "src/application/ice_city_day_page.py",
    "src/application/catalog_home_page.py",
)
_BARE_WEEKEND = re.compile(r"Выходные")


def _js_copy() -> dict[str, str]:
    text = _JS_PATH.read_text(encoding="utf-8")
    match = re.search(r"var COPY = (\{.*?\});", text, re.DOTALL)
    assert match, "glide-copy.js: не нашли литерал COPY"
    return json.loads(match.group(1))


@lru_cache(maxsize=1)
def _glide_copy_t() -> dict[str, str]:
    """Каждый ключ JSON прогнан через ``GlideCopy.t()``, не через сырой объект COPY."""
    script = r"""
const GC = require('./static/webapp/glide-copy.js');
const keys = Object.keys(require('./src/shared/copy_ru.json'));
const out = {};
for (const key of keys) out[key] = GC.t(key);
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_json_python_and_js_copy_match_key_for_key() -> None:
    json_copy = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    js_copy = _js_copy()
    assert json_copy == COPY
    assert json_copy == js_copy


@pytest.mark.parametrize("key", sorted(COPY))
def test_every_key_resolves_the_same_in_python_and_glide_copy_t(key: str) -> None:
    """AC-1: значение ключа из copy_ru.json одинаково в t() и GlideCopy.t()."""
    assert t(key) == _glide_copy_t()[key]


def test_palette_literals_stay_in_glide_tokens() -> None:
    """AC-2: в шаблонах сайта и Mini App нет литералов палитры вне glide-tokens.css."""
    tokens = (_REPO_ROOT / "static" / "shared" / "glide-tokens.css").read_text(encoding="utf-8")
    for literal in _PALETTE_LITERALS:
        assert literal in tokens.lower(), literal
    for rel in _PALETTE_TEMPLATES:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8").lower()
        found = [literal for literal in _PALETTE_LITERALS if literal in text]
        assert not found, f"{rel}: {found}"


def test_tg_dark_fallback_overrides_the_same_variables() -> None:
    """Telegram без themeParams: body.tg-dark задаёт свою палитру тем же --g-*."""
    css = (_REPO_ROOT / "static" / "shared" / "glide-tokens.css").read_text(encoding="utf-8")
    root = re.search(r":root\s*\{([^}]*)\}", css)
    dark = re.search(r"body\.tg-dark\s*\{([^}]*)\}", css)
    assert root and dark

    def _value(block: str, name: str) -> str:
        match = re.search(rf"{re.escape(name)}:\s*([^;]+);", block)
        assert match, name
        return match.group(1).strip()

    for name in ("--g-bg", "--g-surface", "--g-ink", "--g-muted", "--g-line", "--g-accent"):
        assert _value(dark.group(1), name) != _value(root.group(1), name), name


def test_time_menu_has_no_bare_weekend_label() -> None:
    """AC-3: «Выходные» без «В» не осталось в меню времени сайта и Mini App."""
    hits: list[str] = []
    for rel in _TIME_MENU_PATHS:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        if _BARE_WEEKEND.search(text):
            hits.append(rel)
    assert hits == []


def test_minimum_keys_present() -> None:
    required = {
        "when.today",
        "when.tomorrow",
        "when.weekend",
        "when.day",
        "when.evening",
        "basis.live",
        "basis.projected",
        "basis.projected_long",
        "basis.photo",
        "mode.phone",
        "mode.season_closed",
        "mode.reopen",
        "kind.public_skate",
        "kind.hockey_practice",
        "cta.follow",
        "cta.follow_closed",
        "cta.following",
        "cta.metoo",
        "cta.call",
        "cta.route",
        "cta.share",
        "cta.report",
        "price.with_rental",
        "footer.made_by",
    }
    assert required <= set(COPY)


def test_when_weekend_is_the_aligned_wording() -> None:
    """Раньше Mini App говорил «В выходные» в одном месте и «Выходные» в другом (TASK-209)."""
    assert t("when.weekend") == "В выходные"


def test_t_formats_placeholders() -> None:
    assert t("mode.reopen", date="12 октября") == "Откроется 12 октября"
    assert t("price.with_rental", total="25", currency="BYN") == "с прокатом 25 BYN"


def test_t_without_kwargs_returns_raw_template() -> None:
    assert t("mode.reopen") == "Откроется {date}"
