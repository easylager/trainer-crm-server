"""Алерт админам: матч Экстралиги с ходами игроков остаётся без итога дольше четырёх часов (TASK-359).

Что уже закрыто другими алертами и здесь не дублируется:

* матч Динамо (КХЛ) без итога через 3 ч 30 мин уходит в ``review`` с одним алертом (``check_due_results``);
* матч Экстралиги, ушедший в ``review``, получает карточку с кнопками (``notify_new_reviews``).

Не закрыт случай Экстралиги, где матч остаётся ``scheduled``: страница hockey.by молчит или второй опрос с тем
же счётом так и не пришёл, а календарь не отдал итог. Статус не меняется, ``review`` не наступает, и о матче
с ходами никто не знает. Для него и цикл: одно сообщение с кнопкой «Поправить» (админ присылает счёт).

Дедупликация — ``review_alerted_at``, тот же флаг, что у остальных алертов матча: второго сообщения нет ни от
этого цикла, ни от карточки проверки (админ уже в курсе). Флага отдельно снимать не нужно: матч с итогом
(``final``) в выборку не попадает.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.application.hockey_matches import AUTO_CONFIRM_WINDOW
from src.application.hockey_review import CB_FIX, probe_title
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

# Позже автоподтверждение невозможно, а раньше итог может быть просто ещё в пути: четыре часа от старта,
# запасной итог из календаря Экстралиги срабатывает на шестом (CALENDAR_RESULT_AFTER).
STUCK_AFTER = timedelta(hours=4)

Sender = Callable[[str, list[list[dict]]], Awaitable["bool | None"]]

# Только Экстралига в статусе scheduled и только матчи, на которые есть хотя бы один ход: без ходов итог
# ставится сразу, очки считать не из чего. Окно в три дня не даёт на первом запуске завалить админов историей.
_STUCK = text("""
    SELECT m.id, m.home_team, m.away_team, m.starts_at, m.result_probe AS probe,
           (SELECT COUNT(*) FROM hockey_picks AS p WHERE p.match_id = m.id)::int AS picks
    FROM hockey_matches AS m
    WHERE m.league = 'extraliga' AND m.status = 'scheduled' AND m.review_alerted_at IS NULL
      AND m.starts_at <= :late AND m.starts_at >= :window_start
      AND EXISTS (SELECT 1 FROM hockey_picks AS p WHERE p.match_id = m.id)
    ORDER BY m.starts_at, m.id
    """)

_ALERTED = text("UPDATE hockey_matches SET review_alerted_at = :now WHERE id = :id AND review_alerted_at IS NULL")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def stuck_text(row, *, now: datetime) -> str:
    when = _utc(row.starts_at).astimezone(MINSK_TZ).strftime("%d.%m %H:%M")
    hours = int((_utc(now) - _utc(row.starts_at)).total_seconds() // 3600)
    seen = probe_title(row.probe)
    last = f"Последний опрос hockey.by: {seen}" if seen else "hockey.by итог не показал"
    return (
        f"<b>Экстралига: итога нет уже {hours} ч</b>\n"
        f"{html.escape(row.home_team)} — {html.escape(row.away_team)}, {when}\n"
        f"Ходов игроков: {row.picks}. {last}\n"
        "Если матч сыгран, пришлите счёт кнопкой «Поправить»."
    )


def stuck_buttons(match_id: int) -> list[list[dict]]:
    return [[{"text": "Поправить", "callback_data": f"{CB_FIX}:{match_id}"}]]


async def notify_stuck_results(session_factory, *, now: datetime, send: Sender) -> int:
    """По одному сообщению на матч, который стал «зависшим». Возвращает, сколько отправлено.

    Админ-бот недоступен (``send`` вернул ``False``) — флаг не ставится, повтор на следующем тике.
    """
    now = _utc(now)
    params = {"late": now - STUCK_AFTER, "window_start": now - AUTO_CONFIRM_WINDOW}
    async with session_factory() as session:
        rows = (await session.execute(_STUCK, params)).all()
    sent = 0
    for row in rows:
        delivered = await send(stuck_text(row, now=now), stuck_buttons(row.id))
        if delivered is False:
            continue
        async with session_factory() as session:
            await session.execute(_ALERTED, {"id": row.id, "now": now})
            await session.commit()
        sent += 1
    if sent:
        logger.info("[hockey_stuck] alerted %s match(es) without a result", sent)
    return sent


__all__ = ["STUCK_AFTER", "notify_stuck_results", "stuck_buttons", "stuck_text"]
