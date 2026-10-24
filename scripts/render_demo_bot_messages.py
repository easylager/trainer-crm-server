"""
Сообщения ботов демо-тренера (TASK-325) — как они выглядят в Telegram.

Текст и кнопки берутся из тех же функций, что вызывают циклы уведомлений
(``src/bot/notification_loops.py``), на данных демо-базы — ничего не дописывается руками:

* ``trainer-new-booking``  — «Новая запись» тренеру (``run_booking_notifier_loop``);
* ``client-reminder``      — напоминание родителю «занятие завтра» (``run_reminder_loop``);
* ``trainer-weekly-digest``— воскресная сводка тренеру (``run_weekly_digest_loop``).

Каждое сообщение пишется отдельной HTML-страницей в стиле чата Telegram (светлая тема).
Шапка чата («Glide», «бот») и время отправки — оформление, а не текст продукта.

Запуск — после ``scripts/seed_demo_trainer.py``, с той же базой::

    DATABASE_URL=postgresql+asyncpg://…/landing_shots_325 \\
        .venv/bin/python scripts/render_demo_bot_messages.py OUT_DIR
"""

from __future__ import annotations

import asyncio
import html
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Кнопка «Кабинет» в сводке строится только для https-базы — подставляем прод-домен.
if not os.environ.get("WEBAPP_BASE_URL", "").startswith("https://"):
    os.environ["WEBAPP_BASE_URL"] = "https://glideclub.by"

from sqlalchemy import text  # noqa: E402

from scripts.seed_demo_trainer import AS_OF_TIME, DEMO_TRAINER_TG  # noqa: E402

MINSK = ZoneInfo("Europe/Minsk")


def _buttons(markup) -> list[list[str]]:
    if markup is None:
        return []
    return [[b.text for b in row] for row in markup.inline_keyboard]


async def _new_booking(session, trainer_id: int) -> dict:
    from src.application.booking_use_cases import get_bookings_pending_notification
    from src.bot import messages as msg
    from src.bot.notification_loops import _booking_pending_notify_keyboard
    from src.shared.currency import resolve_trainer_currency
    from src.shared.public_display import format_phone_display

    pending = [b for b in await get_bookings_pending_notification(session) if int(b["trainer_id"]) == trainer_id]
    if not pending:
        sys.exit("Нет новой записи без уведомления — сначала запустите seed_demo_trainer.py")
    b = pending[0]
    currency = await resolve_trainer_currency(session, trainer_id)
    phone_raw = (b.get("client_phone") or "").strip()
    body = msg.format_trainer_new_booking_html(
        client_name=b.get("client_name") or "Ученик",
        slot_date=b["slot_date"],
        start_time=b["start_time"],
        service=b.get("service_name"),
        arena=b.get("arenas_str"),
        price=msg.money_text(b.get("booking_price_cents"), currency) or (b.get("price_tier_label") or ""),
        phone=format_phone_display(phone_raw) if phone_raw and not b.get("client_telegram_id") else None,
        comment=b.get("client_comment"),
        first_online=bool(b.get("is_first_client_online_booking")),
    )
    kb = _booking_pending_notify_keyboard(int(b["id"]), client_tid=b.get("client_telegram_id"),
                                          trainer_tid=DEMO_TRAINER_TG)
    created = b.get("created_at")
    stamp = created.astimezone(MINSK).strftime("%H:%M") if isinstance(created, datetime) else "06:56"
    return {"html": body, "buttons": _buttons(kb), "time": stamp}


async def _client_reminder(session, trainer_id: int, tomorrow: date) -> dict:
    from aiogram.types import InlineKeyboardButton

    from src.application.booking_payment_notice import enrich_booking_dicts_with_expected_payment_class
    from src.application.booking_use_cases import fetch_reminder_session_cards_map
    from src.bot import messages as msg
    from src.bot.notification_loops import _reminder_duration_minutes, _slot_display_strings
    from src.shared.map_links import build_yandex_by_map_url

    # Ближайшая завтрашняя запись ребёнка (профиль без своего Telegram — пишем родителю).
    bid = (
        await session.execute(
            text(
                """
                SELECT b.id FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                JOIN clients c ON c.id = b.client_id
                WHERE b.trainer_id = :t AND b.status = 'confirmed' AND s.slot_date = :d
                  AND c.telegram_id IS NULL AND s.training_group_id IS NULL
                ORDER BY s.start_time LIMIT 1
                """
            ),
            {"t": trainer_id, "d": tomorrow},
        )
    ).scalar()
    if bid is None:
        sys.exit(f"Нет записи ребёнка на {tomorrow} — проверьте сид")
    snap = await fetch_reminder_session_cards_map(session, [int(bid)])
    await enrich_booking_dicts_with_expected_payment_class(session, list(snap.values()), booking_id_key="booking_id")
    s = snap[int(bid)]
    date_str, day_str, time_str = _slot_display_strings(s.get("slot_date"), s.get("start_time"))
    dur = s.get("duration_minutes")
    if dur is None:
        dur = _reminder_duration_minutes(s.get("start_time"), s.get("end_time"))
    payload = {
        "date": date_str, "day": day_str, "time": time_str, "duration": int(dur or 0),
        "service_name": s.get("service_name"), "booking_price_cents": s.get("booking_price_cents"),
        "expected_payment_class": s.get("expected_payment_class"), "arena_name": s.get("arena_name"),
        "arena_address": s.get("arena_address"), "booked_for_name": s.get("booked_for_name"),
        "arena_tickets_url": s.get("arena_tickets_url"),
    }
    body = msg.format_client_booking_reminder_text(is_soon=False, sessions=[payload])  # kind=before_24h
    rows: list[list[InlineKeyboardButton]] = []
    if s.get("trainer_telegram_id"):
        rows.append([InlineKeyboardButton(text=msg.CLIENT_REMINDER_BTN_WRITE_TRAINER, url="tg://user?id=1")])
    map_url = build_yandex_by_map_url(
        {"latitude": s.get("arena_latitude"), "longitude": s.get("arena_longitude"), "address": s.get("arena_address")}
    )
    if map_url:
        rows.append([InlineKeyboardButton(text=msg.CLIENT_REMINDER_BTN_SHOW_ON_MAP, url=map_url)])
    msg.append_client_booking_tickets_keyboard_row(
        rows, arena_tickets_url=payload["arena_tickets_url"], arena_name=payload["arena_name"]
    )
    st = s.get("start_time")
    stamp = st.strftime("%H:%M") if hasattr(st, "strftime") else "10:00"  # before_24h: за сутки до начала
    return {"html": body, "buttons": [[b.text for b in r] for r in rows], "time": stamp}


async def _weekly_digest(session, trainer_id: int, sunday: date) -> dict:
    from src.application.trainer_digest_use_cases import get_trainer_weekly_digest, resolve_weekly_digest_send_time
    from src.application.trainer_notification_prefs import get_trainer_push_window_bounds
    from src.bot.notification_loops import _digest_overview_keyboard
    from src.bot.trainer_digest_format import format_weekly_digest

    weekly = await get_trainer_weekly_digest(session, trainer_id, sunday)
    start_h, end_h = await get_trainer_push_window_bounds(session, trainer_id)
    send_at = resolve_weekly_digest_send_time(push_window_start_hour=start_h, push_window_end_hour=end_h)
    return {"html": format_weekly_digest(weekly), "buttons": _buttons(_digest_overview_keyboard()),
            "time": send_at.strftime("%H:%M")}


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#dfe6d6; --bubble:#ffffff; --text:#000; --hint:#8e8e93; --link:#2481cc; --bar:#f7f7f7; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  html, body {{ height:100%; }}
  body {{ font: 17px/1.32 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
         color:var(--text); background:var(--bg);
         background-image: radial-gradient(circle at 20% 10%, #e9efd9 0, transparent 40%),
                           radial-gradient(circle at 80% 60%, #d2dfcb 0, transparent 45%);
         display:flex; flex-direction:column; -webkit-font-smoothing:antialiased; }}
  header {{ background:var(--bar); border-bottom:.5px solid #c8c7cc; padding:10px 14px 9px;
           display:flex; align-items:center; gap:10px; }}
  .back {{ color:var(--link); font-size:17px; width:62px; }}
  .who {{ flex:1; text-align:center; }}
  .who b {{ display:block; font-size:16px; font-weight:600; }}
  .who span {{ font-size:13px; color:var(--hint); }}
  .ava {{ width:36px; height:36px; border-radius:50%; background:linear-gradient(160deg,#5ad1c8,#2a9d97);
         color:#fff; font-weight:700; font-size:16px; display:grid; place-items:center; margin-left:26px; }}
  main {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end; padding:12px 10px 14px; gap:6px; }}
  .day {{ align-self:center; font-size:13px; color:#fff; background:rgba(0,0,0,.22); border-radius:12px;
         padding:3px 10px; margin-bottom:6px; }}
  .msg {{ max-width:92%; align-self:flex-start; }}
  .bubble {{ background:var(--bubble); border-radius:18px 18px 18px 6px; padding:8px 12px 7px;
            box-shadow:0 1px 1px rgba(0,0,0,.08); white-space:pre-wrap; overflow-wrap:anywhere; }}
  .bubble a {{ color:var(--link); text-decoration:none; }}
  .t {{ float:right; font-size:12px; color:var(--hint); margin:8px 0 -4px 10px; }}
  .kb {{ display:flex; flex-direction:column; gap:4px; margin-top:4px; }}
  .kb div {{ display:flex; gap:4px; }}
  .kb span {{ flex:1; text-align:center; font-size:15px; font-weight:500; color:#fff; padding:9px 6px;
             border-radius:10px; background:rgba(60,80,60,.36); backdrop-filter:blur(6px); }}
  footer {{ background:var(--bar); border-top:.5px solid #c8c7cc; padding:8px 12px 26px; display:flex; gap:10px;
           align-items:center; }}
  footer .in {{ flex:1; background:#fff; border:.5px solid #c8c7cc; border-radius:18px; padding:7px 14px;
               color:var(--hint); font-size:16px; }}
  footer .menu {{ background:var(--link); color:#fff; border-radius:8px; padding:6px 10px; font-size:15px; font-weight:600; }}
</style></head>
<body>
<header><span class="back">‹ Чаты</span><div class="who"><b>Glide</b><span>бот</span></div><div class="ava">G</div></header>
<main>
  <div class="day">{day}</div>
  <div class="msg"><div class="bubble">{body}<span class="t">{time}</span></div>{kb}</div>
</main>
<footer><span class="menu">Меню</span><span class="in">Сообщение</span></footer>
</body></html>
"""

_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
           "ноября", "декабря"]


def _page(title: str, day: date, m: dict) -> str:
    kb = ""
    if m["buttons"]:
        kb = '<div class="kb">' + "".join(
            "<div>" + "".join(f"<span>{html.escape(lbl)}</span>" for lbl in row) + "</div>" for row in m["buttons"]
        ) + "</div>"
    # Телеграм рендерит parse_mode=HTML: <b>, <i>, <a>, переносы строк — те же теги, что в тексте.
    return PAGE.format(title=title, day=f"{day.day} {_MONTHS[day.month - 1]}", body=m["html"].strip(),
                       time=m["time"], kb=kb)


async def main(out_dir: Path) -> None:
    from src.infrastructure.db.session import async_session_factory

    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(MINSK).date()
    mon = today - timedelta(days=today.weekday())
    async with async_session_factory() as session:
        trainer_id = (
            await session.execute(text("SELECT id FROM trainers WHERE telegram_id = :tg"), {"tg": DEMO_TRAINER_TG})
        ).scalar()
        if trainer_id is None:
            sys.exit("Демо-тренер не найден — запустите scripts/seed_demo_trainer.py")
        trainer_id = int(trainer_id)
        new_booking = await _new_booking(session, trainer_id)
        reminder = await _client_reminder(session, trainer_id, today + timedelta(days=1))
        # Сводка уходит в воскресенье; берём воскресенье перед текущей неделей:
        # прошлая неделя — проведённые занятия, впереди — текущая неделя демо-тренера.
        digest = await _weekly_digest(session, trainer_id, mon - timedelta(days=1))
        await session.rollback()

    pages = {
        "trainer-new-booking.html": ("Новая запись", today, new_booking),
        "client-reminder.html": ("Напоминание", today, reminder),
        "trainer-weekly-digest.html": ("Сводка недели", mon - timedelta(days=1), digest),
    }
    for name, (title, day, m) in pages.items():
        (out_dir / name).write_text(_page(title, day, m), encoding="utf-8")
        print(f"{name}: {m['time']} buttons={m['buttons']}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "tmp/demo-bot-messages")))
