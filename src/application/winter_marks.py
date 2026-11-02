"""Отметки людей о зимней точке и пересчёт статуса (TASK-343).

Статус = чистая функция от отметок (``winter_status.compute_state``); строка
``seasonal_rink_seasons`` — её кэш. Любая запись отметки берёт ``FOR UPDATE`` на строку сезона,
поэтому две одновременные отметки не создают два перехода «залит» и две рассылки.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared import winter_status as ws

logger = logging.getLogger(__name__)

FLOOD_EVENT_COOLDOWN = timedelta(hours=24)  # не больше одного повода рассылки на точку в сутки
SITE_DAILY_LIMIT = 10  # отметок с одного устройства/сети в сутки по всем точкам
SITE_MINUTE_POINTS = 3  # разных точек в минуту
ACCOUNT_MIN_AGE = timedelta(days=7)
ADMIN_CONFIRM_SHIELD = timedelta(days=30)


class MarkError(Exception):
    def __init__(self, code: str, retry_after_sec: int | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after_sec = retry_after_sec


@dataclass
class MarkResult:
    arena_id: int
    state: str
    state_changed: bool
    quality: str | None
    duplicate: bool = False
    flood_event_id: int | None = None
    dispute: bool = False
    pending_confirm: bool = False  # люди набрали «залит», ждём админа; публично «ждём заливку»


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now


async def _lock_season(session: AsyncSession, arena_id: int, season: int):
    return (
        await session.execute(
            text(
                """SELECT s.id, s.state, s.state_source, s.state_at, s.dispute, s.doubtful, s.admin_confirmed_at,
                          s.pending_confirm, s.flood_floor_at
                   FROM seasonal_rink_seasons s
                   JOIN arenas a ON a.id = s.arena_id AND a.is_active
                   WHERE s.arena_id = :a AND s.season = :s
                   FOR UPDATE OF s"""
            ),
            {"a": arena_id, "s": season},
        )
    ).first()


async def _load_marks(session: AsyncSession, arena_id: int, season: int, now: datetime) -> list[ws.MarkIn]:
    rows = (
        await session.execute(
            text(
                """SELECT kind, value, weight, actor, created_at, source FROM seasonal_rink_marks
                   WHERE arena_id = :a AND season = :s AND created_at >= :since"""
            ),
            {"a": arena_id, "s": season, "since": now - ws.FLOODED_WINDOW},
        )
    ).all()
    return [ws.MarkIn(r.kind, r.value, float(r.weight), r.actor, r.created_at, r.source) for r in rows]


async def _open_item(session: AsyncSession, kind: str, arena_id: int, ref_id: int | None = None) -> None:
    await session.execute(
        text("INSERT INTO seasonal_moderation_items (kind, arena_id, ref_id) VALUES (:k, :a, :r) ON CONFLICT DO NOTHING"),
        {"k": kind, "a": arena_id, "r": ref_id},
    )


async def _close_items(session: AsyncSession, kind: str, arena_id: int, resolution: str, by: int | None = None) -> None:
    await session.execute(
        text(
            """UPDATE seasonal_moderation_items SET status='done', resolution=:r, resolved_at=now(), resolved_by=:by
               WHERE kind=:k AND arena_id=:a AND status='open'"""
        ),
        {"k": kind, "a": arena_id, "r": resolution, "by": by},
    )


async def recompute_point(session: AsyncSession, arena_id: int, season: int, now: datetime) -> MarkResult | None:
    """Пересчитать и сохранить статус. ``None`` — у точки нет сезонной записи."""
    row = await _lock_season(session, arena_id, season)
    if row is None:
        return None
    marks = await _load_marks(session, arena_id, season, now)
    comp = ws.compute_state(
        marks, now, row.state, prev_source=row.state_source, prev_at=row.state_at, floor=row.flood_floor_at
    )
    changed = comp.state != row.state
    event_id: int | None = None
    if changed:
        await session.execute(
            text(
                """UPDATE seasonal_rink_seasons SET state=:st, state_at=:now, state_source='engine',
                   quality=:q, dispute=:d, pending_confirm=:pc, updated_at=now() WHERE id=:id"""
            ),
            {"st": comp.state, "now": now, "q": comp.quality, "d": comp.dispute, "pc": comp.pending_confirm, "id": row.id},
        )
    else:
        await session.execute(
            text("UPDATE seasonal_rink_seasons SET quality=:q, dispute=:d, pending_confirm=:pc, updated_at=now() WHERE id=:id"),
            {"q": comp.quality, "d": comp.dispute, "pc": comp.pending_confirm, "id": row.id},
        )
    # Рассылку «залили» движок не запускает никогда: только админ или парсер (set_state_admin / set_state_source).
    if comp.pending_confirm:
        await _open_item(session, "confirm_flood", arena_id)
    elif row.pending_confirm:
        await _close_items(session, "confirm_flood", arena_id, "auto")
    if comp.dispute:
        await _open_item(session, "dispute", arena_id)
    elif row.dispute:
        await _close_items(session, "dispute", arena_id, "auto")
    return MarkResult(arena_id, comp.state, changed, comp.quality, dispute=comp.dispute, flood_event_id=event_id,
                      pending_confirm=comp.pending_confirm)


async def _flood_event(session: AsyncSession, arena_id: int, season: int, now: datetime) -> int | None:
    recent = (
        await session.execute(
            text("SELECT 1 FROM winter_flood_events WHERE arena_id=:a AND flooded_at > :since LIMIT 1"),
            {"a": arena_id, "since": now - FLOOD_EVENT_COOLDOWN},
        )
    ).first()
    if recent:
        return None
    return int(
        (
            await session.execute(
                text("INSERT INTO winter_flood_events (arena_id, season, flooded_at) VALUES (:a, :s, :n) RETURNING id"),
                {"a": arena_id, "s": season, "n": now},
            )
        ).scalar_one()
    )


async def record_mark(
    session: AsyncSession,
    *,
    arena_id: int,
    kind: str,
    value: str,
    source: str,
    actor: str,
    telegram_id: int | None = None,
    photo_id: int | None = None,
    idem_key: str | None = None,
    weight: float | None = None,
    now: datetime | None = None,
    skip_site_limits: bool = False,
) -> MarkResult:
    """Записать отметку и пересчитать статус. Commit — на вызывающем.

    ``skip_site_limits`` — для попутных отметок той же шторки (людей, хоккей): лимит «1 в 3 ч на точку»
    уже проверен на главной отметке про лёд, иначе вторая отметка шторки всегда получала бы 429.
    """
    now = _utc(now)
    if source not in ws.SOURCES:
        raise MarkError("bad_source")
    if not ws.is_valid_mark(kind, value):
        raise MarkError("bad_value")
    season = ws.current_season(now)
    row = await _lock_season(session, arena_id, season)
    if row is None or row.state == ws.STATE_HIDDEN:
        raise MarkError("not_found")  # скрытые, кандидаты и неактивные не принимают отметок
    if idem_key:
        dup = (
            await session.execute(
                text("SELECT 1 FROM seasonal_rink_marks WHERE actor=:a AND idem_key=:k"), {"a": actor, "k": idem_key}
            )
        ).first()
        if dup:
            return MarkResult(arena_id, row.state, False, None, duplicate=True)
    if source == ws.SOURCE_SITE and not skip_site_limits:
        await _site_limits(session, actor, arena_id, now)
    w = ws.weight_for(source) if weight is None else float(weight)
    await session.execute(
        text(
            """INSERT INTO seasonal_rink_marks
               (arena_id, season, kind, value, source, weight, actor, telegram_id, photo_id, idem_key, created_at)
               VALUES (:a, :s, :k, :v, :src, :w, :actor, :tg, :ph, :idem, :n)"""
        ),
        {"a": arena_id, "s": season, "k": kind, "v": value, "src": source, "w": w, "actor": actor,
         "tg": telegram_id, "ph": photo_id, "idem": idem_key, "n": now},
    )
    result = await recompute_point(session, arena_id, season, now)
    assert result is not None
    return result


async def _site_limits(session: AsyncSession, actor: str, arena_id: int, now: datetime) -> None:
    last = (
        await session.execute(
            text("SELECT max(created_at) FROM seasonal_rink_marks WHERE actor=:a AND arena_id=:p"),
            {"a": actor, "p": arena_id},
        )
    ).scalar_one()
    if not ws.site_mark_allowed(last, now):
        wait = int((ws.SITE_REPEAT_LIMIT - (now - last)).total_seconds())
        raise MarkError("rate_limited", retry_after_sec=max(wait, 1))
    day = (
        await session.execute(
            text("SELECT count(*) FROM seasonal_rink_marks WHERE actor=:a AND created_at > :s"),
            {"a": actor, "s": now - timedelta(days=1)},
        )
    ).scalar_one()
    if int(day) >= SITE_DAILY_LIMIT:
        raise MarkError("rate_limited", retry_after_sec=3600)
    minute = (
        await session.execute(
            text(
                "SELECT count(DISTINCT arena_id) FROM seasonal_rink_marks WHERE actor=:a AND created_at > :s"
            ),
            {"a": actor, "s": now - timedelta(minutes=1)},
        )
    ).scalar_one()
    if int(minute) >= SITE_MINUTE_POINTS:
        raise MarkError("rate_limited", retry_after_sec=60)


# --- админ ---------------------------------------------------------------------
async def set_state_admin(
    session: AsyncSession, arena_id: int, state: str, *, admin_id: int | None, now: datetime | None = None,
    source: str = "admin",
) -> bool:
    """Админ (или официальный источник, ``source='parser'``) ставит статус руками.

    ``flooded`` держится 7 суток и единственный даёт повод для рассылки «залили». Решение закрывает запрос
    «подтвердить заливку»; отметки людей до этого момента уже учтены и новый запрос не поднимают.
    """
    now = _utc(now)
    if state not in ws.STATES:
        raise MarkError("bad_state")
    if source not in ws.CONFIRMED_SOURCES:
        raise MarkError("bad_source")
    season = ws.current_season(now)
    row = await _lock_season(session, arena_id, season)
    if row is None:
        return False
    await session.execute(
        text(
            """UPDATE seasonal_rink_seasons SET state=CAST(:st AS varchar), state_at=:n, state_source=CAST(:src AS varchar),
               admin_confirmed_at = CASE WHEN CAST(:src AS varchar)='admin' THEN :n ELSE admin_confirmed_at END,
               flood_floor_at=:n, pending_confirm=false,
               hidden_reason = CASE WHEN CAST(:st AS varchar)='hidden' THEN COALESCE(hidden_reason, 'admin') ELSE NULL END,
               doubtful=false, updated_at=now() WHERE id=:id"""
        ),
        {"st": state, "n": now, "id": row.id, "src": source},
    )
    await _close_items(session, "confirm_flood", arena_id, state, admin_id)
    if state == ws.STATE_FLOODED and row.state != ws.STATE_FLOODED:
        await _flood_event(session, arena_id, season, now)
    return True


async def set_state_source(
    session: AsyncSession, arena_id: int, state: str, *, now: datetime | None = None
) -> bool:
    """Парсер / официальный источник сообщает статус: «залит» верим сразу, рассылка уходит."""
    return await set_state_admin(session, arena_id, state, admin_id=None, now=now, source="parser")


async def ask_more(session: AsyncSession, arena_id: int, *, admin_id: int | None, now: datetime | None = None) -> bool:
    """«Спросить ещё»: статус не трогаем, запрос закрываем с пометкой; следующая отметка «залит» поднимет новый."""
    now = _utc(now)
    season = ws.current_season(now)
    row = await _lock_season(session, arena_id, season)
    if row is None:
        return False
    await _close_items(session, "confirm_flood", arena_id, "ask_more", admin_id)
    await session.execute(
        text("UPDATE seasonal_rink_seasons SET flood_floor_at=:n, pending_confirm=false, updated_at=now() WHERE id=:id"),
        {"n": now, "id": row.id},
    )
    return True


# --- «точки больше нет» -----------------------------------------------------------
@dataclass
class GoneResult:
    counted: bool
    reason: str | None = None
    queued: str | None = None  # gone | dispute


async def signal_gone(
    session: AsyncSession, *, arena_id: int, telegram_id: int | None, now: datetime | None = None
) -> GoneResult:
    """Сигнал «точки больше нет». Сайт не считается; аккаунт должен быть старше 7 дней.

    3 сигнала от 3 разных людей за 7 дней -> «под вопросом» + очередь админа. Если у точки
    живой статус «залит» или админ подтверждал её за 30 дней — спор, а не пометка.
    Точка сама не скрывается никогда.
    """
    now = _utc(now)
    if telegram_id is None:
        return GoneResult(False, "login_required")
    season = ws.current_season(now)
    row = await _lock_season(session, arena_id, season)
    if row is None or row.state == ws.STATE_HIDDEN:
        raise MarkError("not_found")
    created = (
        await session.execute(text("SELECT created_at FROM clients WHERE telegram_id = :t"), {"t": telegram_id})
    ).scalar_one_or_none()
    if created is None or now - created < ACCOUNT_MIN_AGE:
        return GoneResult(False, "account_too_new")
    actor = f"tg:{telegram_id}"
    reset = (
        await session.execute(text("SELECT gone_reset_at FROM seasonal_rinks WHERE arena_id=:a"), {"a": arena_id})
    ).scalar_one_or_none()
    since = max(now - ws.GONE_WINDOW, reset) if reset else now - ws.GONE_WINDOW
    already = (
        await session.execute(
            text("SELECT 1 FROM seasonal_rink_signals WHERE arena_id=:a AND actor=:x AND created_at > :s"),
            {"a": arena_id, "x": actor, "s": since},
        )
    ).first()
    if not already:
        await session.execute(
            text("INSERT INTO seasonal_rink_signals (arena_id, actor, created_at) VALUES (:a, :x, :n)"),
            {"a": arena_id, "x": actor, "n": now},
        )
    n = int(
        (
            await session.execute(
                text("SELECT count(DISTINCT actor) FROM seasonal_rink_signals WHERE arena_id=:a AND created_at > :s"),
                {"a": arena_id, "s": since},
            )
        ).scalar_one()
    )
    if not ws.gone_signals_reached(n):
        return GoneResult(True)
    shielded = row.state == ws.STATE_FLOODED or (
        row.admin_confirmed_at is not None and now - row.admin_confirmed_at < ADMIN_CONFIRM_SHIELD
    )
    if shielded:
        await _open_item(session, "dispute", arena_id)
        return GoneResult(True, queued="dispute")
    await session.execute(
        text("UPDATE seasonal_rink_seasons SET doubtful = true, updated_at = now() WHERE id = :id"), {"id": row.id}
    )
    await _open_item(session, "gone", arena_id)
    return GoneResult(True, queued="gone")


async def resolve_gone(
    session: AsyncSession, arena_id: int, *, point_exists: bool, admin_id: int | None, now: datetime | None = None
) -> None:
    """Решение админа: точки нет -> скрыть; точка есть -> снять «под вопросом» и обнулить счёт сигналов."""
    now = _utc(now)
    if point_exists:
        await session.execute(
            text("UPDATE seasonal_rinks SET gone_reset_at=:n WHERE arena_id=:a"), {"n": now, "a": arena_id}
        )
        await session.execute(
            text(
                """UPDATE seasonal_rink_seasons SET doubtful=false, admin_confirmed_at=:n, updated_at=now()
                   WHERE arena_id=:a AND season=:s"""
            ),
            {"n": now, "a": arena_id, "s": ws.current_season(now)},
        )
        resolution = "kept"
    else:
        await session.execute(
            text(
                """UPDATE seasonal_rink_seasons SET state='hidden', state_source='admin', state_at=:n, doubtful=false,
                   hidden_reason='gone', updated_at=now() WHERE arena_id=:a AND season=:s"""
            ),
            {"n": now, "a": arena_id, "s": ws.current_season(now)},
        )
        resolution = "hidden"
    await _close_items(session, "gone", arena_id, resolution, admin_id)
    await _close_items(session, "dispute", arena_id, resolution, admin_id)


async def recompute_stale(session: AsyncSession, now: datetime | None = None) -> int:
    """Фоновый проход: у «залит» без свежих отметок статус уходит в «давно не отмечали»."""
    now = _utc(now)
    season = ws.current_season(now)
    ids = (
        await session.execute(
            text(
                """SELECT arena_id FROM seasonal_rink_seasons
                   WHERE season=:s AND (state IN ('flooded', 'stale') OR pending_confirm) AND state_at < :cut"""
            ),
            {"s": season, "cut": now - timedelta(hours=1)},
        )
    ).scalars().all()
    changed = 0
    for aid in ids:
        res = await recompute_point(session, int(aid), season, now)
        changed += 1 if res and res.state_changed else 0
    return changed
