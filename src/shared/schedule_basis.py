"""Происхождение расписания сеанса (TASK-179): live / projected / photo / manual."""
from __future__ import annotations

from typing import Any, Mapping

SCHEDULE_BASIS_LIVE = "live"
SCHEDULE_BASIS_PROJECTED = "projected"
SCHEDULE_BASIS_PHOTO = "photo"
SCHEDULE_BASIS_MANUAL = "manual"

SCHEDULE_BASIS_VALUES = (
    SCHEDULE_BASIS_LIVE,
    SCHEDULE_BASIS_PROJECTED,
    SCHEDULE_BASIS_PHOTO,
    SCHEDULE_BASIS_MANUAL,
)

# Парсеры, которые не снимают расписание с сайта на дату (см. TASK-179).
PARSER_DEFAULT_SCHEDULE_BASIS: dict[str, str] = {
    "brest_lds_v1": SCHEDULE_BASIS_PROJECTED,
    "zamok_html_v1": SCHEDULE_BASIS_PROJECTED,
    "junost_instagram_caption_v1": SCHEDULE_BASIS_PHOTO,
    "lida_lds_v1": SCHEDULE_BASIS_PHOTO,
}

_BASIS_HINT_RU: dict[str, str] = {
    SCHEDULE_BASIS_PROJECTED: "Обычная сетка катка — уточняйте по телефону",
    SCHEDULE_BASIS_PHOTO: "Расписание с фото или поста — уточняйте по телефону",
    SCHEDULE_BASIS_MANUAL: "Внесено вручную — уточняйте по телефону",
}


def normalize_schedule_basis(value: str | None) -> str:
    raw = (value or SCHEDULE_BASIS_LIVE).strip().lower()
    if raw in SCHEDULE_BASIS_VALUES:
        return raw
    return SCHEDULE_BASIS_LIVE


def basis_for_parser_job(parser_key: str, config: Mapping[str, Any] | None) -> str:
    cfg = config or {}
    explicit = cfg.get("schedule_basis")
    if explicit:
        return normalize_schedule_basis(str(explicit))
    return PARSER_DEFAULT_SCHEDULE_BASIS.get(parser_key, SCHEDULE_BASIS_LIVE)


def basis_for_admin_source(source_id: str | None) -> str | None:
    sid = (source_id or "").strip()
    if sid in ("admin",) or sid.startswith("etalon_"):
        return SCHEDULE_BASIS_MANUAL
    return None


def resolve_schedule_basis(
    *,
    parser_key: str,
    job_config: Mapping[str, Any] | None,
    extraction_basis: str | None,
    source_id: str | None = None,
) -> str:
    manual = basis_for_admin_source(source_id)
    if manual:
        return manual
    if extraction_basis:
        return normalize_schedule_basis(extraction_basis)
    return basis_for_parser_job(parser_key, job_config)


def basis_hint_ru(basis: str | None) -> str | None:
    key = normalize_schedule_basis(basis)
    if key == SCHEDULE_BASIS_LIVE:
        return None
    return _BASIS_HINT_RU.get(key)


def public_basis_css_class(basis: str | None) -> str:
    key = normalize_schedule_basis(basis)
    if key == SCHEDULE_BASIS_LIVE:
        return ""
    return f"slot--basis-{key}"
