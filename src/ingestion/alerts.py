"""Format and send ice-health admin alerts. No HTTP scrape. Admin bot only."""
from __future__ import annotations

import html
import logging
import os
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.health import IceHealthSnapshot, SilentJob, calibration_summary

logger = logging.getLogger(__name__)

_last_silent_alert_date: date | None = None
_last_weekly_digest_date: date | None = None

DIGEST_WEEKDAY_SUNDAY = 6
DIGEST_HOUR_MINSK = 10


def price_totals_grouped_by_currency(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """AC-005: never mix currencies into one total."""
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        code = str(row.get("currency_code") or "").strip().upper()
        if not code:
            continue
        amount = row.get("price_adult_minor")
        if amount is None:
            continue
        totals[code] += int(amount)
    return dict(totals)


def _pct_label(rate: float | None) -> str:
    if rate is None:
        return "н/д"
    return f"{round(rate * 100)}%"


def _share_label(share: float) -> str:
    return f"{round(share * 100)}%"


def format_silent_sources_alert(jobs: list[SilentJob]) -> str:
    if not jobs:
        return "🧊 Молчащих источников нет."
    lines = [
        "<b>🧊 Молчащие источники льда</b>",
        "Нет валидного ok дольше порога (каденс×N) — даже если прогоны не падали.",
        "",
    ]
    for job in jobs[:20]:
        last_ok = job.last_ok_at.isoformat() if job.last_ok_at else "никогда"
        name = html.escape(job.arena_name or f"арена #{job.arena_id}")
        lines.append(
            f"• {name} ({html.escape(job.city_name)}, {html.escape(job.cadence)}) "
            f"last_ok={html.escape(last_ok)} last={html.escape(job.last_status or '—')} "
            f"успех 7д {_pct_label(job.success_rate_7d)} · 30д {_pct_label(job.success_rate_30d)}"
        )
    if len(jobs) > 20:
        lines.append(f"… ещё {len(jobs) - 20}")
    return "\n".join(lines)


def format_weekly_digest(snapshot: IceHealthSnapshot) -> str:
    lines = [
        "<b>🧊 Лёд — еженедельная сводка</b>",
        "",
        "<b>Молчащие источники</b>",
    ]
    if snapshot.silent_jobs:
        for job in snapshot.silent_jobs[:15]:
            name = html.escape(job.arena_name or f"арена #{job.arena_id}")
            last_ok = job.last_ok_at.date().isoformat() if job.last_ok_at else "никогда"
            lines.append(
                f"• {name}: last ok {html.escape(last_ok)}, "
                f"успех 7д {_pct_label(job.success_rate_7d)} / 30д {_pct_label(job.success_rate_30d)}"
            )
    else:
        lines.append("нет")

    lines += ["", "<b>Просроченные факты</b> (доля сеансов с valid_until в прошлом)"]
    if snapshot.stale_by_city:
        for row in snapshot.stale_by_city:
            flag = " ⚠" if row.over_threshold else ""
            lines.append(
                f"• {html.escape(row.city_name)}: {row.stale_count}/{row.total_count} "
                f"({_share_label(row.stale_share)}){flag}"
            )
    else:
        lines.append("нет сеансов с TTL")

    lines += ["", "<b>Уровень A</b> (счётчик рядом с долей, неделя к неделе)"]
    if snapshot.tier_by_city:
        for row in snapshot.tier_by_city:
            delta = row.tier_a_count_delta
            delta_s = f"+{delta}" if delta > 0 else str(delta)
            lines.append(
                f"• {html.escape(row.city_name)}: A {row.tier_a_count}/{row.arenas_total} "
                f"({_share_label(row.tier_a_share)}), было {row.tier_a_count_prev} "
                f"({_share_label(row.tier_a_share_prev)}), Δ {delta_s}"
            )
    else:
        lines.append("нет арен")

    lines += ["", "<b>Плотность записей за 30д</b>"]
    if snapshot.density_by_city:
        for row in snapshot.density_by_city:
            lines.append(
                f"• {html.escape(row.city_name)}: {row.arenas_with_bookings_30d}/{row.arenas_total} "
                f"({_share_label(row.density_share)})"
            )
    else:
        lines.append("нет")

    lines += [
        "",
        f"Ручные правки сеансов за 7д: {snapshot.manual_admin_sessions_7d}",
    ]
    cal = snapshot.calibration if snapshot.calibration is not None else calibration_summary()
    lines.append(_format_calibration_line(cal))
    return "\n".join(lines)


def _format_calibration_line(cal: dict[str, Any] | None) -> str:
    if not cal:
        return "Калибровка точности: н/д"
    overall = cal.get("overall") if isinstance(cal, dict) else None
    if not isinstance(overall, dict) or overall.get("recall") is None:
        return f"Калибровка точности: {html.escape(str(cal))}"
    gold = int(overall.get("gold_count") or 0)
    tp = int(overall.get("true_positives") or 0)
    return (
        f"Калибровка точности: recall {_pct_label(float(overall['recall']))} · "
        f"precision {_pct_label(float(overall.get('precision')))} "
        f"({tp}/{gold})"
    )


async def send_ice_health_to_admins(text_body: str, *, event: str) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.debug("Skipping ice health %s under pytest", event)
        return
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from src.shared.config import Settings

    settings = Settings()
    token = settings.telegram_bot_token_admin
    admin_ids = list(dict.fromkeys(settings.admin_telegram_ids or []))
    if not token or not admin_ids:
        logger.warning("Admin bot not configured, skipping ice health %s", event)
        return
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for chat_id in admin_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=text_body, disable_web_page_preview=True)
            except Exception:
                logger.exception("failed ice health %s chat_id=%s", event, chat_id)
    finally:
        await bot.session.close()


async def tick_ice_health_alerts(session: AsyncSession, *, now: datetime) -> str | None:
    """Immediate batched alert for newly silent sources / stale-city threshold."""
    global _last_silent_alert_date
    from src.ingestion.health import detect_silent_jobs, stale_session_share_by_city

    silent = await detect_silent_jobs(session, now=now)
    stale = [row for row in await stale_session_share_by_city(session, now=now) if row.over_threshold]
    if not silent and not stale:
        return None
    today = now.date()
    if _last_silent_alert_date == today:
        return None
    parts = []
    if silent:
        parts.append(format_silent_sources_alert(silent))
    if stale:
        lines = ["<b>Просроченные факты выше порога</b>"]
        for row in stale:
            lines.append(
                f"• {html.escape(row.city_name)}: {_share_label(row.stale_share)} "
                f"({row.stale_count}/{row.total_count})"
            )
        parts.append("\n".join(lines))
    body = "\n\n".join(parts)
    await send_ice_health_to_admins(body, event="ice health alert")
    _last_silent_alert_date = today
    return body


def _minsk_now(now: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
    from src.shared.notification_hours import NOTIFICATION_TZ

    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    return now.astimezone(ZoneInfo(NOTIFICATION_TZ))


async def _calibration_for_digest() -> dict[str, Any] | None:
    """Run gold-set scoring only on the weekly tick — not on every admin page load."""
    try:
        from src.ingestion.calibration import metrics_for_digest, run_calibration

        report = await run_calibration()
        return metrics_for_digest(report)
    except Exception:
        logger.exception("ice calibration for weekly digest failed")
        return None


async def tick_ice_health_weekly_digest(session: AsyncSession, *, now: datetime) -> str | None:
    """One Sunday message: silent sources, stale share, A count next to share."""
    global _last_weekly_digest_date
    from src.ingestion.health import ice_health_snapshot

    local = _minsk_now(now)
    if local.weekday() != DIGEST_WEEKDAY_SUNDAY:
        return None
    if local.hour < DIGEST_HOUR_MINSK:
        return None
    today = local.date()
    if _last_weekly_digest_date == today:
        return None
    snap = await ice_health_snapshot(session, now=now)
    cal = await _calibration_for_digest()
    if cal is not None:
        snap = replace(snap, calibration=cal)
    body = format_weekly_digest(snap)
    await send_ice_health_to_admins(body, event="ice health weekly digest")
    _last_weekly_digest_date = today
    return body


__all__ = [
    "DIGEST_HOUR_MINSK",
    "DIGEST_WEEKDAY_SUNDAY",
    "format_silent_sources_alert",
    "format_weekly_digest",
    "price_totals_grouped_by_currency",
    "send_ice_health_to_admins",
    "tick_ice_health_alerts",
    "tick_ice_health_weekly_digest",
]
