"""Load vertical/market landing manifest for Ice Pro public site."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.shared.config import Settings

_LANDING_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "landing"
_VERTICALS_DIR = _LANDING_DIR / "verticals"
_FALLBACK_MANIFEST = _VERTICALS_DIR / "ice.by.json"


def manifest_path_for(vertical: str, market: str) -> Path:
    """Resolve manifest file; fall back to ice.by when vertical/market combo is missing."""
    v = (vertical or "ice").strip().lower()
    m = (market or "by").strip().lower()
    candidate = _VERTICALS_DIR / f"{v}.{m}.json"
    if candidate.is_file():
        return candidate
    return _FALLBACK_MANIFEST


@lru_cache(maxsize=16)
def _load_manifest_file(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_landing_manifest(settings: Settings | None = None) -> dict[str, Any]:
    """Full manifest merged with runtime env (vertical, market, registration flag)."""
    s = settings or Settings()
    vertical = (s.landing_vertical or "ice").strip().lower()
    market = (s.landing_market or "by").strip().lower()
    path = manifest_path_for(vertical, market)
    data = dict(_load_manifest_file(str(path.resolve())))
    data["vertical"] = vertical
    data["market"] = market
    data["registration_enabled"] = bool(s.landing_trainer_registration_enabled)
    return data


def public_landing_config(settings: Settings | None = None) -> dict[str, Any]:
    """Public slice for API and client hydration — no secrets."""
    m = load_landing_manifest(settings)
    return {
        "vertical": m.get("vertical"),
        "market": m.get("market"),
        "brand": m.get("brand"),
        "hero": m.get("hero"),
        "value_pillars": m.get("value_pillars"),
        "sections": m.get("sections"),
        "activation_arc": m.get("activation_arc"),
        "bento": m.get("bento"),
        "steps": m.get("steps"),
        "cta": m.get("cta"),
        "stats_labels": m.get("stats_labels"),
        "visual": m.get("visual"),
        "footer": m.get("footer"),
        "registration_enabled": m.get("registration_enabled"),
    }


def inject_landing_html(html: str, settings: Settings | None = None) -> str:
    """SSR: data attributes on <html> + JSON bootstrap script before </head>."""
    m = load_landing_manifest(settings)
    cfg = public_landing_config(settings)
    cfg_json = json.dumps(cfg, ensure_ascii=False)
    vertical = m.get("vertical", "ice")
    market = m.get("market", "by")

    html = html.replace(
        "<html",
        f'<html data-vertical="{vertical}" data-market="{market}"',
        1,
    )
    bootstrap = (
        f'  <script id="landing-config" type="application/json">{cfg_json}</script>\n'
    )
    marker = "</head>"
    if marker not in html:
        raise ValueError("landing index.html must contain </head>")
    return html.replace(marker, bootstrap + marker, 1)


def clear_landing_manifest_cache_for_tests() -> None:
    """Tests only — reload manifests after file edits."""
    _load_manifest_file.cache_clear()
