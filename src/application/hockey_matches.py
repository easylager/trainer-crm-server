"""Матчи Динамо-Минск для «Кто кого»: календарь, подтверждённый итог, ручной ввод (TASK-296).

Итог публикуется, только когда счёт со страницы hcdinamo.by совпал с завершённым матчем в ленте
hockey.by — вместе с тем, как решён матч (основное время, овертайм, буллиты). Расхождение или
нет подтверждения через 4 часа после начала — матч уходит на ручную проверку, админу алерт.
Официальный итог при победе по буллитам — +1 гол победителю, как на обоих сайтах.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.hockey_sources import (
    DECIDED_OT,
    DECIDED_REGULATION,
    DECIDED_SO,
    HCDINAMO_BASE,
    HCDINAMO_CALENDAR_URL,
    HOCKEY_BY_URL,
    MINSK_TZ,
    HcdinamoMatch,
    TickerResult,
    parse_hcdinamo_calendar,
    parse_hcdinamo_match,
    parse_hockey_by_ticker,
)

logger = logging.getLogger(__name__)

SOURCE_HCDINAMO = "hcdinamo"
DINAMO = "Динамо-Минск"
TICKER_DINAMO = "Динамо Мн"
TICKER_LEAGUE_KHL = "КХЛ"

STATUS_SCHEDULED = "scheduled"
STATUS_FINAL = "final"
STATUS_REVIEW = "review"
STATUS_CANCELLED = "cancelled"

RESULT_AUTO = "auto"
RESULT_MANUAL = "manual"

# Матч КХЛ с перерывами идёт около 2,5 часа; раньше двух часов итог не ищем.
RESULT_CHECK_AFTER = timedelta(hours=2)
REVIEW_AFTER = timedelta(hours=4)
# Лента hockey.by держит матчи за пару дней — дальше автоматом не подтвердить.
AUTO_CONFIRM_WINDOW = timedelta(days=3)

DECIDED_VALUES = (DECIDED_REGULATION, DECIDED_OT, DECIDED_SO)
_DECIDED_LABEL = {DECIDED_REGULATION: "в основное время", DECIDED_OT: "в овертайме", DECIDED_SO: "по буллитам"}

Fetch = Callable[[str], Awaitable[str]]
AlertSender = Callable[[str], Awaitable[bool | None]]

KIND_WAIT = "wait"
KIND_FINAL = "final"
KIND_REVIEW = "review"


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    decided_in: str | None = None


def match_url(source_match_id: str) -> str:
    return f"{HCDINAMO_BASE}/matches/{source_match_id}/"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _find_ticker(ticker: list[TickerResult], starts_at: datetime) -> TickerResult | None:
    local_day = starts_at.astimezone(MINSK_TZ).date()
    for item in ticker:
        if item.league == TICKER_LEAGUE_KHL and item.local_date == local_day and TICKER_DINAMO in item.teams:
            return item
    return None


def decide_result(
    page: HcdinamoMatch | None,
    ticker: list[TickerResult],
    *,
    starts_at: datetime,
    now: datetime,
) -> Decision:
    """Чистое решение по одному матчу: ждать, публиковать итог или звать человека."""
    starts_at, now = _utc(starts_at), _utc(now)
    if now < starts_at + RESULT_CHECK_AFTER:
        return Decision(KIND_WAIT)

    candidate = page if page is not None and page.looks_final else None
    confirm = _find_ticker(ticker, starts_at)

    if candidate is not None and confirm is not None and confirm.completed:
        if DINAMO not in (candidate.home, candidate.away):
            return Decision(KIND_REVIEW, reason="на странице матча нет Динамо-Минск")
        dinamo_home = candidate.home == DINAMO
        ours = (
            (candidate.home_score, candidate.away_score)
            if dinamo_home
            else (candidate.away_score, candidate.home_score)
        )
        idx = confirm.teams.index(TICKER_DINAMO)
        theirs = (confirm.points[idx], confirm.points[1 - idx])
        if ours != theirs:
            return Decision(
                KIND_REVIEW,
                reason=f"счёт не совпал: hcdinamo.by {ours[0]}:{ours[1]}, hockey.by {theirs[0]}:{theirs[1]} (Динамо первым)",
            )
        if confirm.decided_in != candidate.decided_in:
            return Decision(
                KIND_REVIEW,
                reason=(
                    f"не совпало, как решён матч: hcdinamo.by {_DECIDED_LABEL.get(candidate.decided_in or '', '?')}, "
                    f"hockey.by {_DECIDED_LABEL[confirm.decided_in]}"
                ),
            )
        return Decision(
            KIND_FINAL,
            home_score=candidate.home_score,
            away_score=candidate.away_score,
            decided_in=candidate.decided_in,
        )

    if now >= starts_at + REVIEW_AFTER:
        if candidate is None:
            return Decision(KIND_REVIEW, reason="на hcdinamo.by нет итогового счёта")
        return Decision(KIND_REVIEW, reason="hockey.by не подтвердил, что матч завершён")
    return Decision(KIND_WAIT)


_COLUMNS = (
    "id, source_match_id, home_team, away_team, starts_at, status, home_score, away_score,"
    " decided_in, result_source, review_reason, review_alerted_at"
)

_SELECT_BY_SOURCE = text(f"""
    SELECT {_COLUMNS} FROM hockey_matches
    WHERE source = :source AND source_match_id = :source_match_id
    """)

_INSERT = text("""
    INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status, checked_at)
    VALUES (:source, :source_match_id, :home_team, :away_team, :starts_at, 'scheduled', :now)
    """)

_MOVE = text("""
    UPDATE hockey_matches
    SET starts_at = :starts_at, home_team = :home_team, away_team = :away_team, updated_at = :now
    WHERE id = :id AND status = 'scheduled'
    """)

_TOUCH = text("UPDATE hockey_matches SET checked_at = :now WHERE id = :id")

_FINAL = text("""
    UPDATE hockey_matches
    SET status = 'final', home_score = :home_score, away_score = :away_score, decided_in = :decided_in,
        result_source = :result_source, finalized_at = :now, review_reason = NULL,
        checked_at = :now, updated_at = :now
    WHERE id = :id
    """)

_REVIEW = text("""
    UPDATE hockey_matches
    SET status = 'review', review_reason = :reason, checked_at = :now, updated_at = :now
    WHERE id = :id
    """)

_ALERTED = text("UPDATE hockey_matches SET review_alerted_at = :now WHERE id = :id")

_SELECT_ONE = text(f"SELECT {_COLUMNS} FROM hockey_matches WHERE id = :id")

_DUE = text(f"""
    SELECT {_COLUMNS} FROM hockey_matches
    WHERE status IN ('scheduled', 'review')
      AND starts_at <= :check_before
      AND starts_at >= :window_start
    ORDER BY starts_at
    """)


@dataclass(frozen=True)
class MatchRow:
    id: int
    source_match_id: str
    home_team: str
    away_team: str
    starts_at: datetime
    status: str
    home_score: int | None
    away_score: int | None
    decided_in: str | None
    result_source: str | None
    review_reason: str | None
    review_alerted_at: datetime | None


def _row(record) -> MatchRow:
    return MatchRow(**record._mapping)


async def get_match(session: AsyncSession, match_id: int) -> MatchRow | None:
    record = (await session.execute(_SELECT_ONE, {"id": match_id})).one_or_none()
    return None if record is None else _row(record)


async def upsert_calendar_match(session: AsyncSession, page: HcdinamoMatch, *, now: datetime) -> str:
    """Новый матч — вставить; у ещё не сыгранного обновить время и команды. Сыгранный не трогаем."""
    if DINAMO not in (page.home, page.away):
        return "skipped"
    params = {
        "source": SOURCE_HCDINAMO,
        "source_match_id": page.source_match_id,
        "home_team": page.home,
        "away_team": page.away,
        "starts_at": _utc(page.starts_at),
        "now": _utc(now),
    }
    record = (await session.execute(_SELECT_BY_SOURCE, params)).one_or_none()
    if record is None:
        await session.execute(_INSERT, params)
        return "inserted"
    row = _row(record)
    if row.status != STATUS_SCHEDULED:
        return "unchanged"
    if (_utc(row.starts_at), row.home_team, row.away_team) == (params["starts_at"], page.home, page.away):
        return "unchanged"
    await session.execute(_MOVE, {**params, "id": row.id})
    return "moved"


async def apply_decision(session: AsyncSession, row: MatchRow, decision: Decision, *, now: datetime) -> bool:
    """Записать решение. True — нужен алерт: матч на ручной проверке, алерта ещё не было."""
    now = _utc(now)
    if decision.kind == KIND_FINAL:
        await session.execute(
            _FINAL,
            {
                "id": row.id,
                "home_score": decision.home_score,
                "away_score": decision.away_score,
                "decided_in": decision.decided_in,
                "result_source": RESULT_AUTO,
                "now": now,
            },
        )
        return False
    if decision.kind == KIND_REVIEW:
        await session.execute(_REVIEW, {"id": row.id, "reason": decision.reason, "now": now})
        return row.review_alerted_at is None
    await session.execute(_TOUCH, {"id": row.id, "now": now})
    return False


def validate_result(home_score: int, away_score: int, decided_in: str) -> None:
    if decided_in not in DECIDED_VALUES:
        raise ValueError("Как решён матч: основное время, овертайм или буллиты")
    if home_score < 0 or away_score < 0:
        raise ValueError("Счёт не может быть отрицательным")
    if home_score == away_score:
        raise ValueError("В хоккее ничьих нет: с буллитами победителю +1 гол")
    if decided_in != DECIDED_REGULATION and abs(home_score - away_score) != 1:
        raise ValueError("В овертайме и по буллитам разница ровно в одну шайбу")


async def set_manual_result(
    session: AsyncSession,
    match_id: int,
    *,
    home_score: int,
    away_score: int,
    decided_in: str,
    now: datetime,
) -> MatchRow:
    """Ручной ввод админа закрывает матч так же, как автомат, и сильнее его."""
    validate_result(home_score, away_score, decided_in)
    if await get_match(session, match_id) is None:
        raise LookupError(match_id)
    await session.execute(
        _FINAL,
        {
            "id": match_id,
            "home_score": home_score,
            "away_score": away_score,
            "decided_in": decided_in,
            "result_source": RESULT_MANUAL,
            "now": _utc(now),
        },
    )
    row = await get_match(session, match_id)
    assert row is not None
    return row


async def list_matches(
    session: AsyncSession, *, statuses: tuple[str, ...] | None = None, limit: int = 50
) -> list[MatchRow]:
    where = "WHERE status = ANY(:statuses)" if statuses else ""
    stmt = text(f"SELECT {_COLUMNS} FROM hockey_matches {where} ORDER BY starts_at DESC LIMIT :limit")
    params: dict = {"limit": limit}
    if statuses:
        params["statuses"] = list(statuses)
    return [_row(r) for r in (await session.execute(stmt, params)).all()]


def format_review_alert(row: MatchRow, reason: str | None) -> str:
    when = _utc(row.starts_at).astimezone(MINSK_TZ).strftime("%d.%m %H:%M")
    return (
        f"Кто кого: нет подтверждённого итога\n"
        f"{row.home_team} — {row.away_team}, {when}\n"
        f"{reason or 'причина не записана'}\n"
        f"Введите счёт в админке: /webapp/admin-hockey"
    )


async def sync_calendar(session: AsyncSession, fetch: Fetch, *, now: datetime) -> dict[str, int]:
    """Окно календаря hcdinamo.by → строки матчей. Ошибка одной страницы не роняет остальные."""
    counts: dict[str, int] = {"inserted": 0, "moved": 0, "unchanged": 0, "skipped": 0, "failed": 0}
    ids = parse_hcdinamo_calendar(await fetch(HCDINAMO_CALENDAR_URL))
    for source_match_id in ids:
        try:
            page = parse_hcdinamo_match(await fetch(match_url(source_match_id)), source_match_id=source_match_id)
        except Exception:
            logger.warning("hockey calendar: match %s failed", source_match_id, exc_info=True)
            counts["failed"] += 1
            continue
        counts[await upsert_calendar_match(session, page, now=now)] += 1
    return counts


async def due_for_result(session: AsyncSession, *, now: datetime) -> list[MatchRow]:
    now = _utc(now)
    params = {"check_before": now - RESULT_CHECK_AFTER, "window_start": now - AUTO_CONFIRM_WINDOW}
    return [_row(r) for r in (await session.execute(_DUE, params)).all()]


async def check_due_results(
    session: AsyncSession,
    fetch: Fetch,
    *,
    now: datetime,
    alert: AlertSender,
) -> list[tuple[int, str]]:
    """Один проход по матчам, которым пора иметь итог. Возвращает (id, решение)."""
    rows = await due_for_result(session, now=now)
    if not rows:
        return []
    try:
        ticker = parse_hockey_by_ticker(await fetch(HOCKEY_BY_URL))
    except Exception:
        logger.warning("hockey results: hockey.by failed", exc_info=True)
        ticker = []
    out: list[tuple[int, str]] = []
    for row in rows:
        try:
            page: HcdinamoMatch | None = parse_hcdinamo_match(
                await fetch(match_url(row.source_match_id)), source_match_id=row.source_match_id
            )
        except Exception:
            logger.warning("hockey results: match %s failed", row.source_match_id, exc_info=True)
            page = None
        decision = decide_result(page, ticker, starts_at=row.starts_at, now=now)
        # Матч уже на проверке: причина обновится, второго алерта не будет (review_alerted_at).
        if await apply_decision(session, row, decision, now=now):
            delivered = await alert(format_review_alert(row, decision.reason))
            if delivered is not False:
                await session.execute(_ALERTED, {"id": row.id, "now": _utc(now)})
        out.append((row.id, decision.kind))
    return out


async def send_review_alert(text_body: str) -> bool | None:
    from src.ingestion.alerts import send_ice_health_to_admins

    return await send_ice_health_to_admins(text_body, event="hockey match review")


async def default_fetch(url: str) -> str:
    from src.ingestion.source_io import fetch_http_text

    return await fetch_http_text(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GlideBot/1.0)"})


__all__ = [
    "DECIDED_VALUES",
    "Decision",
    "KIND_FINAL",
    "KIND_REVIEW",
    "KIND_WAIT",
    "apply_decision",
    "check_due_results",
    "decide_result",
    "default_fetch",
    "due_for_result",
    "MatchRow",
    "format_review_alert",
    "get_match",
    "list_matches",
    "match_url",
    "send_review_alert",
    "set_manual_result",
    "sync_calendar",
    "upsert_calendar_match",
    "validate_result",
]
