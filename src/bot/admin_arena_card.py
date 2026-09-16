"""
Shared Telegram card formatting for trainer-created arenas awaiting moderation (TASK-046).

Used by both the pull path (``/pending_arenas`` in admin_handlers) and the push path
(``admin_arena_notify.notify_admins_new_trainer_arena``) so the two stay visually identical.
"""
from __future__ import annotations

import html
from typing import Any


def format_admin_arena_pending_caption(arena: dict[str, Any]) -> str:
    name_esc = html.escape((arena.get("name") or "—").strip())
    address_esc = html.escape((arena.get("address") or "—").strip())
    city_esc = html.escape((arena.get("city_name") or "—").strip())
    coords = arena.get("latitude"), arena.get("longitude")
    coords_str = (
        f"{coords[0]:.5f}, {coords[1]:.5f}" if coords[0] is not None and coords[1] is not None else "не определены"
    )
    trainer_name = html.escape((arena.get("trainer_name") or "").strip())
    trainer_tg = arena.get("trainer_telegram_id")
    trainer_line = trainer_name or (f"id={arena.get('trainer_id')}" if arena.get("trainer_id") else "—")
    if trainer_tg:
        trainer_line += f" (<code>{html.escape(str(trainer_tg))}</code>)"
    coords_missing = arena.get("latitude") is None or arena.get("longitude") is None
    coords_note = (
        "\n⚠️ Автогеокодинг не сработал — «Подтвердить» попросит координаты вручную."
        if coords_missing
        else ""
    )
    return (
        f"<b>Новая арена #{arena['id']}</b>\n"
        f"Название: {name_esc}\n"
        f"Город: {city_esc}\n"
        f"Адрес: {address_esc}\n"
        f"Координаты: {coords_str}\n"
        f"Добавил тренер: {trainer_line}"
        f"{coords_note}"
    )
