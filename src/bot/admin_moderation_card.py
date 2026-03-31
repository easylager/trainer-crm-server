"""
HTML captions for admin trainer moderation (admin bot /pending and async notify).
Single place so card shape stays in sync; user fields are escaped for Telegram HTML.
"""
from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Telegram Bot API: photo caption max length
TELEGRAM_PHOTO_CAPTION_MAX = 1024


async def fetch_city_name(session: AsyncSession, city_id: int | None) -> str | None:
    """Resolve city label for moderation card; None if missing or unknown id."""
    if city_id is None:
        return None
    try:
        r = await session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": int(city_id)})
        row = r.fetchone()
        if not row or not row[0]:
            return None
        return str(row[0]).strip() or None
    except Exception:
        logger.exception("fetch_city_name failed city_id=%s", city_id)
        return None


def _esc_multiline(s: str) -> str:
    return html.escape(s).replace("\n", "<br/>")


def format_admin_education_block(profile: dict, items: list[dict]) -> str:
    """Education for moderation: free-text from profile + structured rows; no per-row moderation status."""
    lines: list[str] = ["", "<b>Образование</b>"]
    edu_free = (profile.get("education") or "").strip()
    if edu_free:
        lines.append(_esc_multiline(edu_free))
    if not items:
        if not edu_free:
            lines.append("— не заполнено")
        return "\n".join(lines)
    if edu_free:
        lines.append("")
    for idx, item in enumerate(items[:10], start=1):
        institution = html.escape((item.get("institution_name") or "—").strip())
        program = html.escape((item.get("program_or_title") or "—").strip())
        lines.append(f"{idx}. {institution} — {program}")
    if len(items) > 10:
        lines.append(f"... и ещё {len(items) - 10}")
    return "\n".join(lines)


def format_admin_trainer_moderation_caption(
    trainer: dict,
    education_items: list[dict],
    *,
    city_name: str | None = None,
) -> str:
    """Full HTML body for one moderation card (photo caption or text message)."""
    profile = trainer.get("profile") or {}
    tid = int(trainer["id"])
    first = (profile.get("first_name") or "").strip()
    last = (profile.get("last_name") or "").strip()
    name_plain = (first + " " + last).strip() or "—"
    name_esc = html.escape(name_plain)

    age = profile.get("age")
    age_str = str(age) if age is not None else "—"
    exp = profile.get("experience_years")
    exp_str = f"{exp} лет" if exp is not None else "не указан"

    tg = trainer.get("telegram_id")
    tg_str = str(tg) if tg is not None else "—"

    city_esc = html.escape(city_name.strip()) if city_name else "—"
    phone_raw = (profile.get("phone") or "").strip()
    phone_esc = html.escape(phone_raw) if phone_raw else "—"
    contacts_raw = (profile.get("contacts") or "").strip()

    sd = profile.get("session_duration_minutes")
    dur_str = f"{sd} мин" if sd is not None else "—"
    mhb = profile.get("min_hours_before_booking")
    mhb_str = f"{mhb} ч" if mhb is not None else "—"

    desc_raw = (profile.get("description") or "").strip() or "—"
    desc_block = _esc_multiline(desc_raw) if desc_raw != "—" else "—"

    parts: list[str] = [
        f"<b>Тренер #{tid}</b>",
        f"Telegram ID: <code>{html.escape(tg_str)}</code>",
        f"Имя: {name_esc}",
        f"Город: {city_esc}",
        f"Возраст: {html.escape(age_str)}",
        f"Опыт: {html.escape(exp_str)}",
        f"Телефон: {phone_esc}",
    ]
    if contacts_raw:
        parts.append(f"Другие контакты: {_esc_multiline(contacts_raw)}")
    parts.append(f"Длительность занятия: {html.escape(dur_str)}")
    parts.append(f"Запись не позднее чем за: {html.escape(mhb_str)}")
    parts.append("")
    parts.append(desc_block)

    services = trainer.get("services") or []
    parts.append("")
    parts.append("<b>Услуги</b>")
    if not services:
        parts.append("— не указаны")
    else:
        for s in services:
            sname = html.escape((s.get("service_name") or "—").strip())
            pb = s.get("price_byn")
            if pb is not None:
                parts.append(f"• {sname} — {html.escape(str(pb))} BYN")
            else:
                parts.append(f"• {sname} — цена не указана")

    arenas = trainer.get("arena_names") or []
    parts.append("")
    parts.append("<b>Площадки</b>")
    if not arenas:
        parts.append("— не указаны")
    else:
        parts.append(html.escape(", ".join(a.strip() for a in arenas if a)) or "—")

    parts.append(format_admin_education_block(profile, education_items))
    return "\n".join(parts)


def split_photo_caption_if_needed(full_caption: str, *, trainer_id: int, name_plain: str) -> tuple[str, str | None]:
    """
    Telegram rejects photo captions over ~1024 chars. If over limit, use a short stub on the photo
    and return the full text as a second message.
    """
    if len(full_caption) <= TELEGRAM_PHOTO_CAPTION_MAX:
        return full_caption, None
    short = (name_plain or "—")[:120]
    stub = (
        f"<b>Тренер #{trainer_id}</b>\n"
        f"{html.escape(short)}\n\n"
        "<i>Полная анкета — следующим сообщением (лимит подписи к фото).</i>"
    )
    return stub, full_caption
