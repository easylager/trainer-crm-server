"""
Human-first share copy for «Поделиться тренером»: unified recommendation text + deep link,
not a naked URL — reads like a quick personal DM, not product referral.
"""

from __future__ import annotations

# Mini App entry points — kept for API/analytics (`share_context`); body copy ignores these.
CLIENT_SHARE_CONTEXT_MY_TRAINER = "my_trainer"
CLIENT_SHARE_CONTEXT_CATALOG = "catalog"
CLIENT_SHARE_CONTEXT_BOOKING_SUCCESS = "booking_success"
CLIENT_SHARE_CONTEXT_NEXT_BOOKING = "next_booking"

CLIENT_SHARE_CONTEXTS = frozenset(
    {
        CLIENT_SHARE_CONTEXT_MY_TRAINER,
        CLIENT_SHARE_CONTEXT_CATALOG,
        CLIENT_SHARE_CONTEXT_BOOKING_SUCCESS,
        CLIENT_SHARE_CONTEXT_NEXT_BOOKING,
    }
)

_SHARE_OPENER = "Вот тренер, к которому я хожу — могу порекомендовать 👇"


def normalize_share_context(raw: str | None) -> str:
    """Defaults unknown/absent values to catalog."""
    if not raw:
        return CLIENT_SHARE_CONTEXT_CATALOG
    s = raw.strip().lower()
    return s if s in CLIENT_SHARE_CONTEXTS else CLIENT_SHARE_CONTEXT_CATALOG


def _specialization_line(service_names: list[str]) -> str | None:
    names = [(n or "").strip() for n in service_names if (n or "").strip()]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    return " · ".join(names[:2])


def _location_line(city_name: str | None, arena_name: str | None) -> str | None:
    parts: list[str] = []
    c = (city_name or "").strip()
    a = (arena_name or "").strip()
    if c:
        parts.append(c)
    if a:
        parts.append(a)
    if not parts:
        return None
    return " · ".join(parts)


def share_body_for_native_share_dialog(full_message: str, deep_link: str) -> str:
    """
    Для `t.me/share/url?url=<deeplink>&text=<body>` текст не должен дублировать URL.

    Обычно полное сообщение начинается с deep link (первая строка); поддерживаем и старый вариант,
    когда ссылка была последней строкой — чтобы не ломать кэш и локальные черновики.
    """
    dl = (deep_link or "").strip()
    if not dl:
        return (full_message or "").strip()
    s = (full_message or "").replace("\r\n", "\n").strip()
    if s.startswith(dl):
        return s[len(dl) :].lstrip("\n").strip()
    if s.endswith(dl):
        return s[: -len(dl)].rstrip().strip()
    return s


def compose_client_share_message(
    *,
    share_context: str,  # noqa: ARG001 — preserved for API; copy is unified across contexts.
    trainer_display_name: str,
    service_names: list[str],
    city_name: str | None,
    primary_arena_name: str | None,
    deep_link: str,
) -> str:
    """
    Полное тело для Telegram share: тем же текстом для любого share_context (хаб, каталог, запись).

    Структура: deep link первой строкой, затем opener → имя → услуги → город · арена.
    """
    dl = deep_link.strip()
    name = (trainer_display_name or "").strip() or "Тренер"
    spec = _specialization_line(service_names)
    loc = _location_line(city_name, primary_arena_name)

    lines: list[str] = [dl, "", _SHARE_OPENER, "", name]
    if spec:
        lines.append(spec)
    if loc:
        lines.append(loc)

    return "\n".join(lines)
