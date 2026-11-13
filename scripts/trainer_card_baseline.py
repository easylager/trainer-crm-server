"""Срез базовой линии карточки тренера (TASK-397). Только чтение.

Запуск из корня репозитория, с DATABASE_URL_SYNC на ту базу, которую смотрим:

    set -a; source .env; set +a
    python scripts/trainer_card_baseline.py
    python scripts/trainer_card_baseline.py --days 14

Просмотры ``/t/<id>`` — люди (``ua_class=human``), по неделе (понедельник, Минск) и метке ``via``.
«Поиск» отдельной меткой не пишется: человек из поисковой выдачи открывает ``/t/`` без ``via``
и попадает в «без via». ``ua_class=search`` — это поисковые боты, они в срез не входят.

Время до подтверждения есть только у записей, подтверждённых после выката этого учёта:
раньше момент подтверждения в базе не хранился.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine, text

from src.application.booking_source import EMPTY_VIA_SQL
from src.application.trainer_card_measure import (
    CONFIRM_LATENCY_SQL,
    CTA_TAPS_SQL,
    FIRST_CONFIRMED_TRAINERS_SQL,
    FIRST_TAP_SQL,
    FUNNEL_EVENTS_SQL,
    SELF_BOOKING_FUNNEL_SQL,
    SITE_WRITE_CLICKS_SQL,
    WEEKLY_SITE_VIEWS_SQL,
)


def _via_label(token: str) -> str:
    if token == "none":
        return "без via"
    if token == "link":
        return "ссылка тренера (link)"
    if token == "share":
        return "рекомендация (share)"
    if token.startswith("k") and token[1:].isdigit():
        return f"каталог k{token[1:]}"
    if token.startswith("p") and token[1:].isdigit():
        return f"каток p{token[1:]}"
    if token.startswith("c") and token[1:].isdigit():
        return f"город c{token[1:]}"
    return token


def _hours(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    return f"{float(seconds) / 3600:.1f} ч"


def main() -> None:
    parser = argparse.ArgumentParser(description="Срез базовой линии карточки тренера (только чтение)")
    parser.add_argument("--days", type=int, default=28, help="окно в днях, по умолчанию 28")
    args = parser.parse_args()
    if args.days < 1 or args.days > 400:
        raise SystemExit("--days от 1 до 400")
    url = (os.environ.get("DATABASE_URL_SYNC") or "").strip()
    if not url:
        raise SystemExit("Нужен DATABASE_URL_SYNC")
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=args.days)
    since_30 = until - timedelta(days=30)
    params = {"since": since, "until": until}
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.exec_driver_sql("SET default_transaction_read_only = ON")
        views = conn.execute(text(WEEKLY_SITE_VIEWS_SQL), params).all()
        ctas = conn.execute(text(CTA_TAPS_SQL), params).all()
        funnel = conn.execute(text(FUNNEL_EVENTS_SQL), params).all()
        latency = conn.execute(text(CONFIRM_LATENCY_SQL), params).one()
        bookings = conn.execute(text(SELF_BOOKING_FUNNEL_SQL), params).one()
        empty = conn.execute(text(EMPTY_VIA_SQL), params).one()
        first_tap = conn.execute(text(FIRST_TAP_SQL), params).all()
        writes = conn.execute(text(SITE_WRITE_CLICKS_SQL), params).one()
        first_trainers = conn.execute(
            text(FIRST_CONFIRMED_TRAINERS_SQL), {"since": since_30, "until": until}
        ).one()

    print(f"Окно: {since.isoformat()} … {until.isoformat()} ({args.days} дн.)")
    print()
    print("Просмотры /t/<id>, люди, по неделе и via")
    print("Поиск отдельно не пишется: заход без метки — «без via». Боты ua_class=search исключены.")
    if not views:
        print("  нет строк")
    for row in views:
        print(f"  {row.week_start}  {row.views:5d}  {_via_label(row.via)}")
    print()
    print("Нажатия кнопок карточки (card_cta_tap)")
    if not ctas:
        print("  нет строк")
    for row in ctas:
        print(f"  {row.surface or '—'}/{row.action or '—'}  {row.taps}")
    print(f"«Написать» на сайте, уже копившееся (public_contact_click, люди): {int(writes.writes or 0)}")
    print()
    print("Воронка событий: форма открыта → отправлена → подтверждена")
    counts = {row.kind: int(row.n) for row in funnel}
    print(f"  форма открыта: {counts.get('booking_form_open', 0)}")
    print(f"  отправлена:    {counts.get('booking_submit', 0)}")
    print(f"  подтверждена:  {counts.get('booking_confirmed', 0)}")
    n = int(latency.n or 0)
    if n == 0:
        print("Время до подтверждения: нет пар (отметка пишется с этого выката)")
    else:
        print(
            f"Время до подтверждения, n={n}: медиана {_hours(latency.p50_seconds)}, "
            f"p90 {_hours(latency.p90_seconds)}"
        )
    print(
        "Самозаписи в окне (bookings.source задан): "
        f"отправлено {int(bookings.submitted or 0)}, "
        f"сейчас confirmed/completed {int(bookings.confirmed or 0)}"
    )
    print(
        "Тренеры, у кого первая подтверждённая запись создана за 30 дней "
        "(по дате создания записи, не по моменту подтверждения): "
        f"{int(first_trainers.trainers or 0)}"
    )
    print()
    self_n = int(empty.self_bookings or 0)
    empty_n = int(empty.empty_via or 0)
    share = f"{empty_n / self_n:.1%}" if self_n else "—"
    print("Доля самозаписей с пустым via (source=unknown / source задан)")
    print(f"  {empty_n} / {self_n} = {share}")
    print(f"  source пустой (запись тренера или строка до колонки), в долю не входит: {int(empty.no_source or 0)}")
    print()
    print("Первое касание после регистрации по ссылке тренера")
    if not first_tap:
        print("  нет строк")
    for row in first_tap:
        print(f"  {row.target or '—'}: {row.n}")


if __name__ == "__main__":
    main()
