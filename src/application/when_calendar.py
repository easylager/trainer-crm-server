"""Календарь «Когда» (TASK-337): лист с семью днями рядом с полосой «Сегодня · Завтра · В выходные».

Один код для главной и хаба города. Лист открывается без JS: кнопка — якорь ``#when-days``,
лист — ``:target``. Числа — тем же предикатом, что счётчики «лёд сегодня»
(``ICE_CITY_DAY_SESSION_WHERE_SQL``), поэтому лист не расходится с главной и хабом.
"""
from __future__ import annotations

import html as html_lib
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_city_day import ICE_CITY_DAY_SESSION_WHERE_SQL, plural_ru
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.ice_time_windows import home_picker_dates
from src.shared.copy_ru import t
from src.shared.ice_discovery_scope import public_scope_params

_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")

_DAY_COUNTS_SQL = text(
    f"""
    SELECT s.local_date AS day, COUNT(*)::int AS n
    FROM ice_sessions s
    JOIN arenas a ON a.id = s.arena_id
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE s.local_date = ANY(:days)
      AND (CAST(:city_id AS integer) IS NULL OR a.city_id = :city_id)
      {ICE_CITY_DAY_SESSION_WHERE_SQL}
    GROUP BY s.local_date
    """
)


async def day_session_counts(
    session: AsyncSession, *, now: datetime, dates: Sequence[date], city_id: int | None = None
) -> dict[date, int]:
    """Сеансов по дням: в стране или в одном городе. Дни без сеансов — ноль."""
    rows = (
        await session.execute(
            _DAY_COUNTS_SQL,
            {"days": list(dates), "city_id": city_id, "now": now, "st": STATUS_ACTIVE, **public_scope_params()},
        )
    ).mappings().all()
    counts = {d: 0 for d in dates}
    for row in rows:
        counts[row["day"]] = int(row["n"])
    return counts


def day_chip_label(d: date) -> str:
    return f"{_WEEKDAYS[d.weekday()]}, {d.day} {_MONTHS[d.month - 1]}"


def _esc(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


_ICON = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<rect x="3.5" y="5" width="17" height="15" rx="3"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>'
)

SHEET_ID = "when-days"


def render_calendar(
    *,
    now: datetime,
    counts: Mapping[date, int],
    selected: date | None,
    href_for: Callable[[date], str],
) -> tuple[str, str]:
    """``(кнопка, лист)``. ``selected`` — выбранный день (подпись на кнопке), иначе значок.

    ``href_for`` строит ссылку на день; страница сама сводит «сегодня» и «завтра» к своим ключам.
    """
    if selected is not None:
        button = (
            f'<a class="b-cal b-cal--day" href="#{SHEET_ID}" aria-current="true" '
            f'aria-label="Выбран день: {_esc(day_chip_label(selected))}. Выбрать другой">'
            f"{_ICON}<span>{_esc(day_chip_label(selected))}</span></a>"
        )
    else:
        button = f'<a class="b-cal" href="#{SHEET_ID}" aria-label="Выбрать день">{_ICON}</a>'
    chips = []
    for d in home_picker_dates(now):
        n = int(counts.get(d, 0))
        classes = "b-dayc" + (" is-off" if n == 0 else "") + (" is-wk" if d.weekday() >= 5 else "")
        cur = ' aria-current="true"' if d == selected else ""
        chips.append(
            f'<a class="{classes}" href="{_esc(href_for(d))}"{cur}>'
            f"<b>{_WEEKDAYS[d.weekday()]}</b><i>{d.day}</i><small>{n if n else '—'}</small></a>"
        )
    sheet = (
        f'<div class="b-sheet" id="{SHEET_ID}" role="dialog" aria-labelledby="{SHEET_ID}-t">'
        f'<a class="b-sheet__bg" href="#" aria-label="Закрыть"></a>'
        f'<div class="b-sheet__panel"><span class="b-sheet__grab" aria-hidden="true"></span>'
        f'<h2 id="{SHEET_ID}-t">{_esc(t("when.pick_day"))}</h2>'
        f'<p class="b-sheet__sub">{_esc(t("when.pick_day_sub"))}</p>'
        f'<div class="b-sheet__grid">{"".join(chips)}</div></div></div>'
    )
    return button, sheet


def sessions_phrase(n: int) -> str:
    return f"{n} {plural_ru(n, 'сеанс', 'сеанса', 'сеансов')}"
