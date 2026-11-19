"""«Кто кого»: пятничное приглашение собрать лигу (TASK-431).

Повод нового движка уведомлений (``kk_notify``): сам ничего не отправляет, только предлагает ``Proposal``; допуск,
бюджет 1 в день и 3 в неделю, тишина 23–09, согласие, «Не присылать» и блокировка — ``kk_notify_gate``.

* Кому: игрок сделал ход за последние 7 суток и у него нет своей действующей лиги (владелец 2026-11-19: в чужой
  лиге состоять можно — зовём создать свою).
* Когда: пятница, 12:00 по Минску (окно до ``WINDOW_TO``, чтобы проход цикла не промахнулся). Приоритет — ниже всех
  поводов игры; итоги ходов и так вне бюджета.
* Серия из трёх недель: неделя N — постер N и текст N (1 «Лига друзей», 2 «Корона каждый месяц», 3 «Свои команды»).
  Стоп: создал свою лигу, отправлено три,
  «Не присылать» (тип ``lginvite`` выключается в настройках игрока).
* Сообщение — фото и подпись, кнопки «Создать лигу друзей» (``kkg_lg<N>`` → экран «Лига готова», метка входа ``lg<N>``
  доходит до ``hockey_entry_events`` и ``hockey_leagues.src``) и «Не присылать».

Выключено по умолчанию (``KK_LEAGUE_INVITE_ENABLED``). Постеры владельца — ``static/share/kk-league-invite-N.png``;
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

# Подписи к постерам владельца (2026-11-19). Неделя 1 — утверждённый текст 2026-11-18 без «2 минут» (жесты убраны
# из релиза); 2 и 3 дописывают постер, а не повторяют его, — ждут утверждения владельца.
WEEK_TEXTS = {
    1: (
        "Собери лигу и договоритесь, на что играете — на пиво, на шашлык или на честь. Каждый вечер видно, "
        "кто угадал лучше и кто носит кепку дня. В конце месяца — корона и расплата."
    ),
    2: (
        "Каждый месяц лучший в лиге забирает корону — и она навсегда остаётся на трибуне победителя. "
        "Собери своих: к весне станет ясно, кто у вас главный."
    ),
    3: (
        "Лигу можно собрать на свои команды: только Динамо, только Юность, пара клубов или всё сразу. "
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
        [hn.url_button("Создать лигу друзей", f"{START_READY}_{src_label(week)}")],
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
      AND NOT EXISTS (SELECT 1 FROM hockey_leagues AS l WHERE l.owner_key = pl.player_key AND l.ends_at > :now)
    ORDER BY pl.player_key
    """)

# Сколько приглашений уже ушло (или заняты и в пути) и когда последнее.
_SERIES = text("""
    SELECT COUNT(*) FILTER (WHERE sent_at IS NOT NULL OR NOT failed)::int AS sent,
           MAX(COALESCE(sent_at, created_at)) AS last_at
    FROM hockey_notices WHERE player_key = :player_key AND kind = 'lginvite'
    """)

# Своя действующая лига появилась — серия кончилась (в чужой лиге состоять можно).
_IN_LEAGUE = text("""
    SELECT EXISTS (SELECT 1 FROM hockey_leagues WHERE owner_key = :player_key AND ends_at > :now)
    """)


async def _series(session: AsyncSession, player_key: int) -> tuple[int, datetime | None]:
    row = (await session.execute(_SERIES, {"player_key": player_key})).one()
    return int(row.sent or 0), row.last_at


def _still_due(week: int):
    """Перед отправкой: всё ещё пятничное окно, игрок без лиги, эта неделя серии не ушла, обложка на месте."""

    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        if not in_window(now):
            return "out_of_window"
        if (await session.execute(_IN_LEAGUE, {"player_key": player_key, "now": now})).scalar_one():
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
