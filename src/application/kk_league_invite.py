"""«Кто кого»: пятничное приглашение собрать лигу (TASK-431).

Повод нового движка уведомлений (``kk_notify``): сам ничего не отправляет, только предлагает ``Proposal``; допуск,
бюджет 1 в день и 3 в неделю, тишина 23–09, согласие, «Не присылать» и блокировка — ``kk_notify_gate``.

* Кому: игрок сделал ход за последние 7 суток и не состоит ни в одной лиге (и своей лиги у него нет).
* Когда: пятница, 12:00 по Минску (окно до ``WINDOW_TO``, чтобы проход цикла не промахнулся). Приоритет — ниже всех
  поводов игры; итоги ходов и так вне бюджета.
* Серия из трёх недель: неделя N — обложка N и текст N. Стоп: создал или вступил в лигу, отправлено три,
  «Не присылать» (тип ``lginvite`` выключается в настройках игрока).
* Сообщение — фото и подпись, кнопки «Собрать лигу» (``kkg_lg<N>`` → экран «Лига готова», метка входа ``lg<N>``
  доходит до ``hockey_entry_events`` и ``hockey_leagues.src``) и «Не присылать».

Выключено по умолчанию (``KK_LEAGUE_INVITE_ENABLED``). Обложки кладёт менеджер в ``static/share/kk-league-invite-N.png``;
нет файла — сообщение этой недели не уходит, в лог пишется предупреждение.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import hockey_notices as hn
from src.application.kk_notify import Proposal
from src.application.kk_notify_gate import KIND_LEAGUE_INVITE
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

FRIDAY = 4
WINDOW_FROM, WINDOW_TO = 12, 14  # окно по Минску: [12:00, 14:00)
SERIES = 3
ACTIVE_DAYS = 7
# Между приглашениями — не меньше недели без суток: в следующую пятницу можно, в эту же — нет.
REPEAT_AFTER = timedelta(days=6)
START_READY = "kkg"  # kkg_<метка> — экран «Лига готова» (glide-deeplink.js, kto-kogo.js)
CB_OFF_INVITE = f"{hn.CB_OFF}:{hn.CODE_OF[KIND_LEAGUE_INVITE]}"
COVERS = Path(__file__).resolve().parents[2] / "static" / "share"

# Тексты недель. Неделя 1 утверждена владельцем 2026-11-18; 2 и 3 — черновики агента, ждут утверждения.
WEEK_TEXTS = {
    1: (
        "Собери лигу и договоритесь, на что играете — на пиво, на шашлык или на честь. Каждый вечер видно, "
        "кто угадал лучше, кто носит кепку, а кого пора удалить на 2 минуты. В конце месяца — корона и расплата."
    ),
    # ЧЕРНОВИК: корона каждый месяц + твои короны на трибуне, чужую трибуну видят все.
    2: (
        "В лиге корона разыгрывается каждый месяц. Забрал — она встаёт на твою трибуну, и её видят все, кто откроет "
        "твой стенд. Собери своих — посмотрим, у кого трибуна к весне будет богаче."
    ),
    # ЧЕРНОВИК: свои команды — Динамо, Юность, несколько или всё сразу.
    3: (
        "Лигу можно собрать на свои команды: только Динамо, только Юность, несколько клубов или всё сразу. "
        "Ходы те же, что в общей игре, — отдельно ходить не нужно, а таблица только для своих."
    ),
}


def cover_path(week: int) -> Path:
    return COVERS / f"kk-league-invite-{week}.png"


def src_label(week: int) -> str:
    return f"lg{week}"


def invite_caption(*, week: int, hits: int, played: int) -> str:
    """Подпись к фото. Первая строка личная — только по сыгранным ходам недели; сыгранных нет — без неё."""
    body = html.escape(WEEK_TEXTS[week])
    if played <= 0:
        return body
    return f"За неделю ты угадал <b>{hits} из {played}</b>. А твои друзья?\n\n{body}"


def invite_buttons(week: int) -> list[list[dict]]:
    return hn._rows(
        [hn.url_button("Собрать лигу", f"{START_READY}_{src_label(week)}")],
        [{"text": "Не присылать", "callback_data": CB_OFF_INVITE}],
    )


def in_window(now: datetime) -> bool:
    local = hn._utc(now).astimezone(MINSK_TZ)
    return local.weekday() == FRIDAY and WINDOW_FROM <= local.hour < WINDOW_TO


# Игроки с ходом за 7 суток, без лиги (ни участником, ни владельцем — своя архивная лига тоже «создал»).
# Последний ход — якорь строки в hockey_notices; сыгранные ходы недели — для личной строки.
_AUDIENCE = text("""
    SELECT pl.player_key,
           (SELECT p.match_id FROM hockey_picks AS p WHERE p.player_key = pl.player_key
            ORDER BY p.picked_at DESC, p.id DESC LIMIT 1) AS anchor,
           (SELECT COUNT(*) FROM hockey_picks AS p JOIN game_matches AS m ON m.id = p.match_id
            WHERE p.player_key = pl.player_key AND m.status = 'final' AND p.points IS NOT NULL
              AND m.starts_at >= :since AND m.starts_at < :now)::int AS played,
           (SELECT COUNT(*) FROM hockey_picks AS p JOIN game_matches AS m ON m.id = p.match_id
            WHERE p.player_key = pl.player_key AND m.status = 'final' AND p.points > 0
              AND m.starts_at >= :since AND m.starts_at < :now)::int AS hits
    FROM hockey_players AS pl
    WHERE EXISTS (SELECT 1 FROM hockey_picks AS p WHERE p.player_key = pl.player_key AND p.picked_at >= :since)
      AND NOT EXISTS (SELECT 1 FROM hockey_league_members AS mb WHERE mb.player_key = pl.player_key)
      AND NOT EXISTS (SELECT 1 FROM hockey_leagues AS l WHERE l.owner_key = pl.player_key)
    ORDER BY pl.player_key
    """)

# Сколько приглашений уже ушло (или заняты и в пути) и когда последнее.
_SERIES = text("""
    SELECT COUNT(*) FILTER (WHERE sent_at IS NOT NULL OR NOT failed)::int AS sent,
           MAX(COALESCE(sent_at, created_at)) AS last_at
    FROM hockey_notices WHERE player_key = :player_key AND kind = 'lginvite'
    """)

_IN_LEAGUE = text("""
    SELECT EXISTS (SELECT 1 FROM hockey_league_members WHERE player_key = :player_key)
        OR EXISTS (SELECT 1 FROM hockey_leagues WHERE owner_key = :player_key)
    """)


async def _series(session: AsyncSession, player_key: int) -> tuple[int, datetime | None]:
    row = (await session.execute(_SERIES, {"player_key": player_key})).one()
    return int(row.sent or 0), row.last_at


def _still_due(week: int):
    """Перед отправкой: всё ещё пятничное окно, игрок без лиги, эта неделя серии не ушла, обложка на месте."""

    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        if not in_window(now):
            return "out_of_window"
        if (await session.execute(_IN_LEAGUE, {"player_key": player_key})).scalar_one():
            return "in_league"
        sent, _ = await _series(session, player_key)
        if sent + 1 != week:
            return "series_moved"
        if not cover_path(week).is_file():
            return "no_cover"
        return None

    return check


def _enabled() -> bool:
    from src.shared.config import Settings

    return bool(Settings().kk_league_invite_enabled)  # type: ignore[call-arg]


async def produce_league_invite(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    if not _enabled() or not in_window(now):
        return []
    now = hn._utc(now)
    out: list[Proposal] = []
    missing: set[int] = set()
    params = {"since": now - timedelta(days=ACTIVE_DAYS), "now": now}
    for r in (await session.execute(_AUDIENCE, params)).all():
        sent, last_at = await _series(session, r.player_key)
        if sent >= SERIES or r.anchor is None:
            continue
        if last_at is not None and hn._utc(last_at) > now - REPEAT_AFTER:
            continue
        week = sent + 1
        cover = cover_path(week)
        if not cover.is_file():
            missing.add(week)
            continue
        notice = hn.Notice(
            KIND_LEAGUE_INVITE,
            r.player_key,
            r.anchor,
            invite_caption(week=week, hits=r.hits, played=r.played),
            invite_buttons(week),
            photo=str(cover),
        )
        out.append(Proposal(notice, _still_due(week)))
    for week in sorted(missing):
        logger.warning("kk league invite: no cover %s, week %s is not sent", cover_path(week), week)
    return out


__all__ = [
    "CB_OFF_INVITE",
    "SERIES",
    "WEEK_TEXTS",
    "cover_path",
    "in_window",
    "invite_buttons",
    "invite_caption",
    "produce_league_invite",
    "src_label",
]
