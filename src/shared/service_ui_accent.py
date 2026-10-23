"""Preset slugs for per-trainer-service UI border accent (hub + schedule)."""

from __future__ import annotations

# Keep in sync with CSS classes: .slot-row--svc-accent-<slug>
SERVICE_UI_ACCENT_SLUGS: frozenset[str] = frozenset(
    {"sky", "amber", "emerald", "violet", "rose", "slate"}
)


def normalize_service_ui_accent(raw: object) -> str | None:
    """Return a valid slug or None (clear / unset)."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if not s:
        return None
    return s if s in SERVICE_UI_ACCENT_SLUGS else None


# Порядок цветов по умолчанию. slate — серый, по умолчанию его не даём: серая карточка и есть
# «безликая», ради которой это сделано.
DEFAULT_SERVICE_UI_ACCENT_ORDER: tuple[str, ...] = ("sky", "amber", "emerald", "violet", "rose")


def with_default_service_ui_accents(accent_by_service_id: dict[int, str | None]) -> dict[int, str]:
    """
    Цвет каждой услуги для карточек записей: выбранный тренером или по умолчанию.

    Выбор цвета жил в старом редакторе профиля; на экране «Услуги и цены» его нет, и услуги
    без цвета рисовались серыми — карточки главной и расписания теряли различимость.
    Услуге без цвета достаётся первый ещё не занятый цвет по порядку id: так цвет услуги не
    прыгает между открытиями, а две услуги не совпадают, пока цветов хватает.
    """
    out: dict[int, str] = {}
    taken: set[str] = set()
    for sid, raw in accent_by_service_id.items():
        slug = normalize_service_ui_accent(raw)
        if slug:
            out[sid] = slug
            taken.add(slug)
    free = [s for s in DEFAULT_SERVICE_UI_ACCENT_ORDER if s not in taken] or list(DEFAULT_SERVICE_UI_ACCENT_ORDER)
    i = 0
    for sid in sorted(accent_by_service_id):
        if sid in out:
            continue
        out[sid] = free[i % len(free)]
        i += 1
    return out
