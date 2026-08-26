"""Load vertical/market landing manifest for Glide public site."""
from __future__ import annotations

import html as html_lib
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
    s = settings or Settings()
    m = load_landing_manifest(s)
    out: dict[str, Any] = {
        "vertical": m.get("vertical"),
        "market": m.get("market"),
        "brand": m.get("brand"),
        "hero": m.get("hero"),
        "seo": m.get("seo"),
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
    if m.get("registration_enabled"):
        uname = (s.trainer_bot_username or "").strip().lstrip("@")
        if uname:
            out["join_url"] = "/join"
            out["telegram_join_url"] = f"https://t.me/{uname}?start=join"
    return out


def _landing_public_base(settings: Settings) -> str:
    return (settings.webapp_base_url or "").strip().rstrip("/")


def _landing_seo_urls(settings: Settings, manifest: dict[str, Any]) -> tuple[str, str]:
    base = _landing_public_base(settings)
    seo = manifest.get("seo") or {}
    canonical_path = (seo.get("canonical_path") or "/").strip()
    if not canonical_path.startswith("/"):
        canonical_path = "/" + canonical_path
    canonical_url = f"{base}{canonical_path}" if base else canonical_path
    og_path = (
        seo.get("og_image")
        or "/logos/02-horizontal-full/glide-horizontal-teal-icon-black-text-on-white.png"
    )
    if not str(og_path).startswith("/"):
        og_path = "/" + str(og_path).lstrip("/")
    if base.lower().startswith("https://"):
        og_image = f"{base}{og_path}"
    else:
        og_image = og_path
    return canonical_url, og_image


def inject_landing_html(html: str, settings: Settings | None = None) -> str:
    """SSR: data attributes on <html>, SEO URLs, JSON bootstrap before </head>."""
    s = settings or Settings()
    m = load_landing_manifest(s)
    cfg = public_landing_config(s)
    cfg_json = json.dumps(cfg, ensure_ascii=False)
    vertical = m.get("vertical", "ice")
    market = m.get("market", "by")
    seo = m.get("seo") or {}
    canonical_url, og_image = _landing_seo_urls(s, m)

    html = html.replace(
        "<html",
        f'<html data-vertical="{vertical}" data-market="{market}"',
        1,
    )
    html = html.replace("__LANDING_CANONICAL__", canonical_url)
    html = html.replace("__LANDING_OG_IMAGE__", og_image)

    if seo.get("title"):
        title_esc = html_lib.escape(str(seo["title"]), quote=True)
        html = html.replace(
            "<title>Glide — CRM для тренера на льду</title>",
            f"<title>{title_esc}</title>",
            1,
        )
        html = html.replace(
            'property="og:title" content="Glide — CRM для тренера на льду"',
            f'property="og:title" content="{title_esc}"',
            1,
        )
        html = html.replace(
            'name="twitter:title" content="Glide — CRM для тренера на льду"',
            f'name="twitter:title" content="{title_esc}"',
            1,
        )
    if seo.get("description"):
        desc_esc = html_lib.escape(str(seo["description"]), quote=True)
        html = html.replace(
            'name="description" content="Glide — CRM для тренера на льду в Telegram. Ссылка на запись, расписание, клиенты и каталог. 14 дней бесплатно."',
            f'name="description" content="{desc_esc}"',
            1,
        )
        html = html.replace(
            'property="og:description" content="Telegram вместо отдельного CRM. Живая ссылка на запись, расписание и каталог Glide — в одном боте."',
            f'property="og:description" content="{desc_esc}"',
            1,
        )
        html = html.replace(
            'name="twitter:description" content="Telegram вместо отдельного CRM. Живая ссылка на запись — ученик сам выбирает слот."',
            f'name="twitter:description" content="{desc_esc}"',
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
