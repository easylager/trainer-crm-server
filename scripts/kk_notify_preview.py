#!/usr/bin/env python3
"""Предпросмотр текстов новых уведомлений «Кто кого» (TASK-426): все поводы и варианты на фикстурных данных.

Без базы и без Telegram: рендерит готовые строки теми же функциями, что отправка (``kk_notify_texts``).
Запуск: ``python scripts/kk_notify_preview.py [--show-nbsp]`` (``--show-nbsp`` рисует неразрывные пробелы как «·»).
"""

from __future__ import annotations

import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.application import kk_notify_texts as tx  # noqa: E402
MINSK_TZ = ZoneInfo("Europe/Minsk")
from src.shared.copy_ru import t  # noqa: E402

DINAMO = "Динамо-Минск"
SOCHI = "Сочи"
SPARTAK = "Спартак"
AK_BARS = "Ак Барс"
TORPEDO = "Торпедо"

NOW_MORNING = datetime(2026, 11, 16, 9, 30, tzinfo=MINSK_TZ)  # понедельник


def at(day: int, hour: int, minute: int = 0, *, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=MINSK_TZ)


def _m(home: str, away: str, starts_at: datetime) -> dict:
    return {"home": home, "away": away, "starts_at": starts_at}


def render_all() -> list[tuple[str, str]]:
    """Список (название варианта, готовый текст)."""
    now = NOW_MORNING
    month_end = datetime(2026, 12, 1, 10, 0, tzinfo=MINSK_TZ)
    out: list[tuple[str, str]] = []

    out.append(("1. Матч сегодня", tx.invite_text(home=DINAMO, away=TORPEDO, starts_at=at(16, 19, 30), now=now)))
    out.append(("1. Матч завтра", tx.invite_text(home=DINAMO, away=TORPEDO, starts_at=at(17, 17), now=now)))

    ak = dict(home=DINAMO, away=AK_BARS, starts_at=at(21, 17), now=now)
    out.append(("2. Возврат, 3 дня", tx.comeback_text(**ak)))
    place = tx.place_line(club=DINAMO, month=11, rank=9, size=21)
    out.append(("2. Возврат, 10 дней, место есть", tx.comeback_text(**ak, place_line_text=place)))
    nope = tx.place_line(club=DINAMO, month=11, rank=15, size=21)
    out.append(("2. Возврат, 10 дней, место не называем (нижняя половина)", tx.comeback_text(**ak, place_line_text=nope)))
    out.append(
        ("2. Возврат, 30 дней", tx.comeback_text(home=DINAMO, away=SOCHI, starts_at=at(3, 19, 30, month=12), now=now))
    )

    nxt = _m(DINAMO, SPARTAK, at(18, 19, 30))
    wk = dict(moves=3, points=60, club=DINAMO, month=11, now=now)
    out.append(("3. Итог недели, место и матч", tx.week_text(**wk, rank=4, size=12, match=nxt)))
    out.append(("3. Итог недели, место, без строки матча", tx.week_text(**wk, rank=4, size=12, match=None)))
    out.append(("3. Итог недели, места нет (мало участников)", tx.week_text(**wk, rank=2, size=4, match=nxt)))
    out.append(("3. Итог недели, 1 ход и 11 очков", tx.week_text(**{**wk, "moves": 1, "points": 11}, rank=1, size=9, match=None)))
    out.append(("3. Итог недели, 21 ход и 105 очков", tx.week_text(**{**wk, "moves": 21, "points": 105}, rank=3, size=9, match=None)))

    mo = dict(month=11, club=DINAMO, points=240, exact=2, now=month_end)
    line = _m(DINAMO, SOCHI, at(3, 19, 30, month=12))
    out.append(("4. Месяц без короны, место", tx.month_text(**mo, rank=3, size=21, crowned=1, i_am_crowned=False, match=line)))
    out.append(("4. Месяц без короны, места нет", tx.month_text(**mo, rank=15, size=21, crowned=1, i_am_crowned=False, match=line)))
    out.append(
        ("4. Месяц без «в точку»", tx.month_text(**{**mo, "exact": 0}, rank=None, size=None, crowned=0, i_am_crowned=False, match=None))
    )
    out.append(("4. Корона одному", tx.month_text(**mo, rank=1, size=21, crowned=1, i_am_crowned=True, match=line)))
    out.append(("4. Корона на двоих", tx.month_text(**mo, rank=1, size=21, crowned=2, i_am_crowned=True, match=line)))
    out.append(("4. Корона общая, трое", tx.month_text(**mo, rank=1, size=21, crowned=3, i_am_crowned=True, match=line)))
    out.append(("4. Корона общая, шестеро", tx.month_text(**mo, rank=1, size=21, crowned=6, i_am_crowned=True, match=None)))

    out.append(("5. Согласие после первого хода", tx.consent_text()))
    return out


def buttons_overview() -> list[str]:
    return [
        "Ход: названия двух команд (кнопки хода)",
        f"«{t('kk_notify.btn.table')}» (ссылка в игру)",
        f"«{t('kk_notify.btn.no')}» (выключает все новые сообщения; итог хода остаётся)",
        f"Согласие: «{t('kk_notify.btn.yes')}» / «{t('kk_notify.btn.no')}»",
    ]


def main(argv: list[str]) -> int:
    show = "--show-nbsp" in argv
    for title, body in render_all():
        text = body.replace("<b>", "**").replace("</b>", "**")
        if show:
            text = text.replace(tx.NBSP, "·")
        print(f"--- {title}\n{text}\n")
    print("--- Кнопки")
    for item in buttons_overview():
        print(f"  {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
