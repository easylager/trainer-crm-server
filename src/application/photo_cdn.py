"""CDN URL helper for catalog photos (TASK-049).

Trainer keys stay under ``trainers/``. Arena media uses ``arenas/``.
``legal/`` and other private prefixes stay rejected.
"""
from __future__ import annotations

from urllib.parse import quote

CDN_KEY_PREFIXES = ("trainers/", "arenas/", "collectives/")


def photo_url_from_cdn(file_key: str | None, base: str | None) -> str | None:
    """Return CDN URL for a storage key, or None if CDN is unset or the key is not public."""
    root = (base or "").strip().rstrip("/")
    key = (file_key or "").strip()
    if not root or not key or ".." in key:
        return None
    if not key.startswith(CDN_KEY_PREFIXES):
        return None
    return root + "/" + quote(key, safe="/")


def visible_photo_url(url: str | None) -> str | None:
    """URL картинки, только если файл на месте. Иначе страница без фото, не битая картинка."""
    raw = str(url or "").strip()
    if not raw.lower().startswith(("https://", "http://", "/")):
        return None
    prefix = "/api/public/photos/"
    if raw.startswith(prefix):
        from urllib.parse import unquote

        from src.infrastructure import s3

        key = unquote(raw[len(prefix) :].split("?", 1)[0])
        return raw if s3.photo_exists(key) else None
    return raw


def public_photo_url(file_key: str | None, cdn_base: str | None = None) -> str | None:
    """CDN URL when configured, else the public photo proxy. Rejects private prefixes."""
    key = (file_key or "").strip()
    if not key or ".." in key or not key.startswith(CDN_KEY_PREFIXES):
        return None
    cdn = photo_url_from_cdn(key, cdn_base)
    if cdn:
        return cdn
    return "/api/public/photos/" + quote(key, safe="/")
