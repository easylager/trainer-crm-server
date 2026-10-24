"""
Демо-тренер для скриншотов лендинга ``/trainers`` (TASK-325).

Вымышленный тренер по катанию на трёх реальных катках Минска: ученики (дети с родителем
и взрослые), заметки и цели, группы, абонемент «5 из 8», неделя занятий — всё относительно
«сегодня», чтобы неделя на кадре всегда была текущей.

Признак демо — фиксированные Telegram id вне реального диапазона (``DEMO_TRAINER_TG`` и
``DEMO_CLIENT_TG_BASE + n``). Тренер не публикуется: ``catalog_state='draft'``,
``is_catalog_visible=false``, ``status='pending_profile'`` (каталог читает только
``status='active'`` + ``catalog_state='published'``).

Идемпотентен: удаляет прежнего демо-тренера и демо-клиентов по этим id и создаёт заново.

Только для локальной/превью-базы. Запуск (БД задаётся явно, общий .env смотрит в общую базу)::

    DATABASE_URL_SYNC=postgresql+psycopg://trainer_crm:trainer_crm_dev@localhost:5432/landing_shots_325 \\
        .venv/bin/python scripts/seed_demo_trainer.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

MINSK = ZoneInfo("Europe/Minsk")
AS_OF_TIME = time(7, 0)

DEMO_TRAINER_TG = 990_000_325
DEMO_CLIENT_TG_BASE = 990_000_400  # +1..+N — родители и взрослые ученики

ARENA_CHIZHOVKA = "Чижовка-арена"
ARENA_ZAMOK = "ТЦ Замок"
ARENA_PALACE = "Ледовый дворец спорта Минской области"

SRV_ZERO = "Обучение катанию «с нуля»"
SRV_IMPROVE = "Совершенствование катания"
SRV_FIGURE = "Фигурное катание"
SRV_HOCKEY = "Хоккейное катание"

TRAINER = {
    "first_name": "Алина",
    "last_name": "Соколовская",
    "experience_years": 9,
    "description": (
        "Учу кататься детей с 4 лет и взрослых с нуля. Фигурное катание — прыжки и вращения "
        "до уровня сальхова и тулупа, хоккейное катание для юных хоккеистов. "
        "Занятия на Чижовке, в «Замке» и Ледовом дворце."
    ),
    "education": "БГУФК, кафедра фигурного катания. КМС по фигурному катанию.",
    "session_duration_minutes": 45,
}

# (service, price BYN, group price BYN, description)
SERVICES = [
    (SRV_ZERO, 45, 25, "Первые шаги на льду: стойка, падение и подъём, «ёлочка», торможение плугом."),
    (SRV_IMPROVE, 50, 25, "Перебежки, ход назад, повороты, торможения — уверенное катание."),
    (SRV_FIGURE, 60, None, "Прыжки и вращения: перекидной, сальхов, тулуп, вращение на одной ноге."),
    (SRV_HOCKEY, 50, 30, "Хоккейное катание: старт, торможение «хоккейной остановкой», crossover."),
]

# key → client. guardian: родитель-контакт (аккаунт Telegram), ребёнок — отдельный профиль.
CLIENTS = [
    {
        "key": "sofia", "first_name": "София", "last_name": "Лапицкая", "child": True,
        "guardian": ("Ирина", "Лапицкая"),
        "level": "Начальный плюс: уверенный ход вперёд, учим ход назад",
        "goals": "Перебежки назад без опоры к ноябрю",
        "season_goal": "Цель к декабрю: сальхов",
        "note": "Держит внешнее ребро. Перебежки вперёд уверенно, назад — с опорой. "
                "Любит, когда занятие заканчивается игрой.",
        "limitations": "Быстро мёрзнут руки — напоминать про варежки",
        "entries": [
            (2, "Перебежки назад с опорой о бортик — 3 круга. Внешнее ребро держит."),
            (6, "Первый самостоятельный перекидной! Приземление на две ноги — работаем."),
            (9, "Вращение на двух ногах 3 оборота. Мама просит добавить занятие в субботу."),
        ],
        "tags": ["фигурное", "абонемент"],
    },
    {
        "key": "misha", "first_name": "Миша", "last_name": "Гурский", "child": True,
        "guardian": ("Андрей", "Гурский"),
        "level": "С нуля, третье занятие",
        "goals": "Торможение плугом → полуплуг",
        "note": "Падает назад — учим группироваться. Стойка стала ниже.",
        "entries": [(3, "Ёлочка 10 м без падений. Торможение плугом с места.")],
        "tags": ["с нуля"],
    },
    {
        "key": "varya", "first_name": "Варвара", "last_name": "Жук", "child": True,
        "guardian": ("Наталья", "Жук"),
        "level": "Группа «Дети 5–7 лет, начинающие»",
        "goals": "Скольжение на одной ноге 3 секунды",
        "note": "Стесняется в группе, на индивидуальном раскрывается.",
        "tags": ["группа"],
    },
    {
        "key": "artem", "first_name": "Артём", "last_name": "Сидоренко", "child": True,
        "guardian": ("Олег", "Сидоренко"),
        "level": "Хоккей, 9 лет, ДЮСШ",
        "goals": "Crossover в обе стороны без потери скорости",
        "note": "Хоккейная остановка влево отлично, вправо — заваливается на внутреннее ребро.",
        "tags": ["хоккей"],
    },
    {
        "key": "ksenia", "first_name": "Ксения", "last_name": "Марченко", "child": False,
        "level": "Взрослая, катается второй сезон",
        "goals": "Уверенный ход назад и торможение «полуплугом»",
        "note": "Боится скорости на поворотах. Хорошо идёт после массового катания, когда лёд пустой.",
        "tags": ["взрослые"],
    },
    {
        "key": "dmitry", "first_name": "Дмитрий", "last_name": "Ковалевич", "child": False,
        "level": "С нуля, взрослый",
        "goals": "Кататься с сыном на массовом без бортика",
        "note": "Торможение плугом → полуплуг. Перебежки вперёд — начали.",
        "tags": ["взрослые", "с нуля"],
    },
    {"key": "polina", "first_name": "Полина", "last_name": "Ярошевич", "child": True,
     "guardian": ("Елена", "Ярошевич"), "level": "Фигурное, 8 лет",
     "goals": "Тулуп в каскаде", "note": "Вращение в ласточке — держит позицию 2 оборота."},
    {"key": "egor", "first_name": "Егор", "last_name": "Василевский", "child": True,
     "guardian": ("Сергей", "Василевский"), "level": "Хоккей, 7 лет",
     "goals": "Старт с места и разгон", "note": "Хорошая скорость, слабая стойка."},
    {"key": "anna", "first_name": "Анна", "last_name": "Петрович", "child": False,
     "level": "Взрослая, с нуля", "goals": "Ёлочка и торможение",
     "note": "По субботам — утренний лёд в Ледовом дворце, пока нет массового."},
    {"key": "lev", "first_name": "Лев", "last_name": "Мицкевич", "child": True,
     "guardian": ("Ольга", "Мицкевич"), "level": "Группа «Дети 5–7 лет, начинающие»",
     "goals": "Ход назад «лимончиком»", "note": "Очень старается, быстро устаёт."},
]

GROUP_KIDS = "Дети 5–7 лет, начинающие"
GROUP_HOCKEY = "Хоккейное катание 8–10 лет"

PASS_PRODUCT = ("Абонемент на 8 занятий", 8, 360, 60)  # name, sessions, BYN, validity days


def _engine():
    url = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Задайте DATABASE_URL_SYNC явно — сид не должен попасть в общую базу.")
    db = url.rsplit("/", 1)[-1]
    if db in {"trainer_crm", "trainer_crm_test"} and not os.environ.get("DEMO_SEED_ALLOW_SHARED"):
        sys.exit(f"Отказ: база {db} — общая. Используйте отдельную (например landing_shots_325).")
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return create_engine(url)


def _one(db: Session, sql: str, **kw):
    return db.execute(text(sql), kw).scalar()


def _id(db: Session, sql: str, **kw) -> int:
    v = _one(db, sql, **kw)
    if v is None:
        sys.exit(f"Не найдено: {sql} {kw}")
    return int(v)


def wipe(s: Session) -> None:
    tid = _one(s, "SELECT id FROM trainers WHERE telegram_id = :tg", tg=DEMO_TRAINER_TG)
    lo, hi = DEMO_CLIENT_TG_BASE, DEMO_CLIENT_TG_BASE + 999
    demo_clients = (
        "SELECT id FROM clients WHERE telegram_id BETWEEN :lo AND :hi "
        "UNION SELECT profile_client_id FROM client_profile_links WHERE account_telegram_id BETWEEN :lo AND :hi"
    )
    ids = [int(r[0]) for r in s.execute(text(demo_clients), {"lo": lo, "hi": hi})]
    if tid is not None:
        # pass_instances → trainer_pass_products без каскада
        s.execute(
            text(
                "DELETE FROM pass_instances WHERE pass_product_id IN "
                "(SELECT id FROM trainer_pass_products WHERE trainer_id = :t)"
            ),
            {"t": tid},
        )
        s.execute(text("UPDATE client_sessions SET selected_trainer_id = NULL WHERE selected_trainer_id = :t"), {"t": tid})
        s.execute(text("DELETE FROM trainers WHERE id = :t"), {"t": tid})
    s.execute(text("DELETE FROM client_profile_links WHERE account_telegram_id BETWEEN :lo AND :hi"), {"lo": lo, "hi": hi})
    s.execute(text("DELETE FROM client_trainer_edges WHERE telegram_id BETWEEN :lo AND :hi"), {"lo": lo, "hi": hi})
    s.execute(text("DELETE FROM client_sessions WHERE telegram_id BETWEEN :lo AND :hi"), {"lo": lo, "hi": hi})
    if ids:
        s.execute(text("DELETE FROM clients WHERE id = ANY(:ids)"), {"ids": ids})


def week_monday(today: date) -> date:
    return today - timedelta(days=today.weekday())


def main() -> None:
    engine = _engine()
    today = datetime.now(MINSK).date()
    # «Сейчас» демо-недели: сегодня 07:00 по Минску. Всё раньше — проведено, позже — подтверждено.
    # Съёмка (scripts/shoot_landing_screens.py) фиксирует часы браузера на тот же момент.
    as_of = datetime.combine(today, AS_OF_TIME, tzinfo=MINSK)
    mon = week_monday(today)
    now_utc = datetime.now(timezone.utc)

    with Session(engine) as s, s.begin():
        wipe(s)

        city = _id(s, "SELECT id FROM cities WHERE name = 'Минск' LIMIT 1")
        arena = {
            k: _id(s, "SELECT id FROM arenas WHERE name = :n AND city_id = :c ORDER BY id LIMIT 1", n=n, c=city)
            for k, n in (("chizh", ARENA_CHIZHOVKA), ("zamok", ARENA_ZAMOK), ("palace", ARENA_PALACE))
        }
        srv = {n: _id(s, "SELECT id FROM services WHERE name = :n AND is_public LIMIT 1", n=n) for n, *_ in SERVICES}

        # --- trainer -------------------------------------------------------------------
        tid = _id(
            s,
            """
            INSERT INTO trainers (telegram_id, status, catalog_state, is_catalog_visible,
                                  primary_arena_id, schedule_grid_step_minutes, created_at)
            VALUES (:tg, 'pending_profile', 'draft', false, :arena, 15, :created)
            RETURNING id
            """,
            tg=DEMO_TRAINER_TG, arena=arena["zamok"], created=now_utc - timedelta(days=120),
        )
        s.execute(
            text(
                """
                INSERT INTO trainer_profiles
                  (trainer_id, first_name, last_name, city_id, experience_years, description, education,
                   session_duration_minutes, min_hours_before_booking, group_classes_enabled,
                   onboarding_completed_at, birth_date)
                VALUES (:t, :fn, :ln, :city, :exp, :d, :edu, :dur, 3, true, :onb, '1993-02-11')
                """
            ),
            {
                "t": tid, "fn": TRAINER["first_name"], "ln": TRAINER["last_name"], "city": city,
                "exp": TRAINER["experience_years"], "d": TRAINER["description"], "edu": TRAINER["education"],
                "dur": TRAINER["session_duration_minutes"], "onb": now_utc - timedelta(days=119),
            },
        )
        plan = _id(s, "SELECT id FROM subscription_plans WHERE NOT is_trial ORDER BY period_days DESC LIMIT 1")
        s.execute(
            text(
                """
                INSERT INTO trainer_subscriptions
                  (trainer_id, plan_id, started_at, expires_at, status, tier, billing_period_months, modules)
                VALUES (:t, :p, :st, :ex, 'active', 'crm', 12,
                        '{"online": true, "analytics": true, "groups": true}'::jsonb)
                """
            ),
            {"t": tid, "p": plan, "st": now_utc - timedelta(days=60), "ex": now_utc + timedelta(days=305)},
        )
        for a in arena.values():
            s.execute(text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:t, :a)"), {"t": tid, "a": a})
        s.execute(text("INSERT INTO trainer_cities (trainer_id, city_id) VALUES (:t, :c) ON CONFLICT DO NOTHING"),
                  {"t": tid, "c": city})
        for name, price, gprice, desc in SERVICES:
            s.execute(
                text(
                    """
                    INSERT INTO trainer_services (trainer_id, service_id, price_cents, group_price_cents, description)
                    VALUES (:t, :s, :p, :g, :d)
                    """
                ),
                {"t": tid, "s": srv[name], "p": price * 100, "g": gprice * 100 if gprice else None, "d": desc},
            )

        # --- clients: взрослые — свой Telegram; дети — профиль без Telegram + родитель-аккаунт ----
        cid: dict[str, int] = {}
        tg_of: dict[str, int] = {}
        for n, c in enumerate(CLIENTS, start=1):
            tg = DEMO_CLIENT_TG_BASE + n
            created = now_utc - timedelta(days=90 - n * 5)
            # Заведомо невыданный диапазон: +375 29 000-xx-xx (у операторов нет префикса 000).
            tg_of[c["key"]] = tg
            phone = f"+37529000{10 + n:02d}{30 + n * 3:02d}"
            if c.get("child"):
                gfn, gln = c["guardian"]
                s.execute(
                    text(
                        "INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized, created_at) "
                        "VALUES (:tg, :fn, :ln, :ph, :pn, :cr)"
                    ),
                    {"tg": tg, "fn": gfn, "ln": gln, "ph": phone, "pn": phone[1:], "cr": created},
                )
                child = _id(
                    s,
                    "INSERT INTO clients (first_name, last_name, phone, created_at) VALUES (:fn, :ln, :ph, :cr) RETURNING id",
                    fn=c["first_name"], ln=c["last_name"], ph=phone, cr=created,
                )
                s.execute(
                    text(
                        "INSERT INTO client_profile_links (account_telegram_id, profile_client_id, role, is_default) "
                        "VALUES (:tg, :cid, 'guardian', true)"
                    ),
                    {"tg": tg, "cid": child},
                )
                cid[c["key"]] = child
            else:
                cid[c["key"]] = _id(
                    s,
                    "INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized, created_at) "
                    "VALUES (:tg, :fn, :ln, :ph, :pn, :cr) RETURNING id",
                    tg=tg, fn=c["first_name"], ln=c["last_name"], ph=phone, pn=phone[1:], cr=created,
                )
            s.execute(
                text("INSERT INTO trainer_client_roster (trainer_id, client_id, created_at) VALUES (:t, :c, :cr)"),
                {"t": tid, "c": cid[c["key"]], "cr": created},
            )
            s.execute(
                text(
                    """
                    INSERT INTO trainer_client_notes (trainer_id, client_id, note, goals, limitations, level,
                                                      season_goal, updated_at)
                    VALUES (:t, :c, :note, :goals, :lim, :lvl, :sg, :upd)
                    """
                ),
                {
                    "t": tid, "c": cid[c["key"]], "note": c.get("note"), "goals": c.get("goals"),
                    "lim": c.get("limitations"), "lvl": c.get("level"), "sg": c.get("season_goal"),
                    "upd": now_utc - timedelta(days=1),
                },
            )
            for days_ago, content in c.get("entries", []):
                s.execute(
                    text(
                        "INSERT INTO trainer_client_entries (trainer_id, client_id, content, created_at) "
                        "VALUES (:t, :c, :x, :cr)"
                    ),
                    {"t": tid, "c": cid[c["key"]], "x": content, "cr": now_utc - timedelta(days=days_ago, hours=3)},
                )
            for tag in c.get("tags", []):
                s.execute(
                    text("INSERT INTO trainer_client_tags (trainer_id, client_id, tag) VALUES (:t, :c, :g)"),
                    {"t": tid, "c": cid[c["key"]], "g": tag},
                )

        # --- groups ------------------------------------------------------------------------
        groups = {
            "kids": (GROUP_KIDS, SRV_ZERO, "chizh", 8, ["varya", "lev", "misha"], [(0, time(17, 15)), (2, time(17, 15)), (4, time(17, 15))]),
            "hockey": (GROUP_HOCKEY, SRV_HOCKEY, "palace", 8, ["artem", "egor"], [(1, time(18, 0)), (5, time(15, 0))]),
        }
        gid: dict[str, int] = {}
        for key, (name, sname, akey, cap, members, rules) in groups.items():
            gid[key] = _id(
                s,
                """
                INSERT INTO training_groups (trainer_id, name, service_id, arena_id, max_members, status,
                                             season_start_date)
                VALUES (:t, :n, :s, :a, :m, 'active', :ss) RETURNING id
                """,
                t=tid, n=name, s=srv[sname], a=arena[akey], m=cap, ss=mon - timedelta(weeks=6),
            )
            for m in members:
                s.execute(
                    text("INSERT INTO training_group_members (training_group_id, client_id, status) VALUES (:g, :c, 'active')"),
                    {"g": gid[key], "c": cid[m]},
                )
            for dow, st in rules:
                s.execute(
                    text(
                        "INSERT INTO training_group_schedule_rules (training_group_id, day_of_week, start_time, "
                        "duration_minutes) VALUES (:g, :d, :st, 60)"
                    ),
                    {"g": gid[key], "d": dow, "st": st},
                )

        price = {name: p for name, p, _g, _d in SERVICES}
        gprice = {name: g for name, _p, g, _d in SERVICES}

        def add_slot(d: date, st: time, minutes: int, akey: str, sname: str, *, group: str | None = None,
                     cap: int = 1, status: str = "available") -> int:
            et = (datetime.combine(d, st) + timedelta(minutes=minutes)).time()
            return _id(
                s,
                """
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id,
                                   arena_id, training_group_id, is_online)
                VALUES (:t, :d, :st, :et, :status, :cap, :s, :a, :g, false) RETURNING id
                """,
                t=tid, d=d, st=st, et=et, status=status, cap=cap, s=srv[sname], a=arena[akey],
                g=gid[group] if group else None,
            )

        def add_booking(slot: int, ckey: str, sname: str, akey: str, d: date, st: time, *, status: str | None = None,
                        group: bool = False, comment: str | None = None) -> int:
            start = datetime.combine(d, st, tzinfo=MINSK)
            if status is None:
                status = "completed" if start < as_of else "confirmed"
            child = next(c for c in CLIENTS if c["key"] == ckey).get("child", False)
            bp = (gprice[sname] if group else price[sname]) or price[sname]
            created = min(start - timedelta(days=3), now_utc - timedelta(hours=2))
            return _id(
                s,
                """
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, arena_id,
                                      booking_price_cents, price_tier_kind, client_comment, created_at, notified_at)
                VALUES (:sl, :t, :c, :s, :st, :a, :bp, :tier, :cm, :cr, :cr) RETURNING id
                """,
                sl=slot, t=tid, c=cid[ckey], s=srv[sname], st=status, a=arena[akey], bp=bp * 100,
                tier="child" if child else "adult", cm=comment, cr=created,
            )

        # --- групповые занятия: 4 прошлые недели + текущая + следующая -----------------------
        for week in range(-4, 2):
            wmon = mon + timedelta(weeks=week)
            for key, (_n, sname, akey, cap, members, rules) in groups.items():
                for dow, st in rules:
                    d = wmon + timedelta(days=dow)
                    sl = add_slot(d, st, 60, akey, sname, group=key, cap=cap)
                    if week <= 0:
                        for m in members:
                            add_booking(sl, m, sname, akey, d, st, group=True)

        # --- индивидуальные: текущая неделя (dow, HH:MM, arena, service, client|None) ----------
        WEEK = [
            (0, "15:30", "zamok", SRV_FIGURE, "sofia"),
            (0, "18:30", "palace", SRV_IMPROVE, "ksenia"),
            (0, "20:15", "chizh", SRV_ZERO, "dmitry"),
            (1, "07:30", "chizh", SRV_HOCKEY, "artem"),
            (1, "16:15", "zamok", SRV_ZERO, "misha"),
            (1, "19:30", "palace", SRV_IMPROVE, None),
            (2, "11:00", "zamok", SRV_ZERO, "anna"),
            (2, "16:00", "palace", SRV_FIGURE, "polina"),
            (2, "20:15", "chizh", SRV_IMPROVE, None),
            (3, "07:30", "chizh", SRV_HOCKEY, "egor"),
            (3, "16:00", "zamok", SRV_FIGURE, "sofia"),
            (3, "18:30", "palace", SRV_FIGURE, None),
            (4, "15:00", "zamok", SRV_ZERO, "misha"),
            (4, "19:00", "palace", SRV_IMPROVE, "ksenia"),
            (4, "20:15", "chizh", SRV_ZERO, "dmitry"),
            (5, "09:00", "chizh", SRV_HOCKEY, "egor"),
            (5, "11:00", "palace", SRV_ZERO, "anna"),
            (5, "13:00", "zamok", SRV_FIGURE, "sofia"),
            (5, "17:00", "palace", SRV_IMPROVE, None),
            (6, "10:00", "chizh", SRV_ZERO, "misha"),
            (6, "12:30", "zamok", SRV_ZERO, "dmitry"),
            (6, "16:45", "palace", SRV_FIGURE, "polina"),
        ]
        # Шаблон недели = те же индивидуальные окна (групповые живут в правилах групп).
        for dow, hhmm, akey, sname, _ckey in WEEK:
            s.execute(
                text(
                    """
                    INSERT INTO trainer_schedule_templates (trainer_id, day_of_week, start_time, duration_minutes,
                                                            capacity, service_id, arena_id)
                    VALUES (:t, :d, :st, :dur, 1, :s, :a)
                    """
                ),
                {"t": tid, "d": dow, "st": time.fromisoformat(hhmm), "dur": TRAINER["session_duration_minutes"],
                 "s": srv[sname], "a": arena[akey]},
            )
        # Регулярные ученики: такие же занятия 4 недели назад (история, абонемент).
        REGULAR = {"sofia", "ksenia", "artem", "misha", "polina", "dmitry", "egor"}
        # Постоянные слоты Софии: пн и чт после школы в «Замке» — автозаписи ссылаются на правило.
        recurring: dict[int, int] = {}
        for dow, hhmm, _a, _s, ckey in WEEK:
            if ckey != "sofia" or dow == 5:
                continue
            st = time.fromisoformat(hhmm)
            et = (datetime.combine(mon, st) + timedelta(minutes=TRAINER["session_duration_minutes"])).time()
            recurring[dow] = _id(
                s,
                "INSERT INTO recurring_client_slots (trainer_id, client_id, day_of_week, start_time, end_time) "
                "VALUES (:t, :c, :d, :st, :et) RETURNING id",
                t=tid, c=cid["sofia"], d=dow, st=st, et=et,
            )
        sofia_done: list[int] = []
        # Прошлые 4 недели — только регулярные; текущая — все; следующая — регулярные записаны,
        # остальные окна свободны (родителю есть куда записаться).
        for week in range(-4, 2):
            for dow, hhmm, akey, sname, ckey in WEEK:
                if week < 0 and ckey not in REGULAR:
                    continue
                if week > 0 and ckey not in REGULAR:
                    ckey = None
                d = mon + timedelta(weeks=week, days=dow)
                st = time.fromisoformat(hhmm)
                sl = add_slot(d, st, TRAINER["session_duration_minutes"], akey, sname,
                              status="booked" if ckey else "available")
                if ckey:
                    b = add_booking(sl, ckey, sname, akey, d, st)
                    if ckey == "sofia" and dow in recurring:
                        s.execute(text("UPDATE bookings SET recurring_client_slot_id = :r WHERE id = :b"),
                                  {"r": recurring[dow], "b": b})
                    if ckey == "sofia" and datetime.combine(d, st, tzinfo=MINSK) < as_of:
                        sofia_done.append(b)
        # Дополнительные свободные окна следующей недели в «Замке» (не пересекаются с записями).
        for dow, hhmm, akey, sname in [(0, "16:30", "zamok", SRV_FIGURE), (1, "15:00", "zamok", SRV_ZERO),
                                       (3, "17:00", "zamok", SRV_FIGURE), (6, "11:15", "zamok", SRV_FIGURE)]:
            add_slot(mon + timedelta(weeks=1, days=dow), time.fromisoformat(hhmm),
                     TRAINER["session_duration_minutes"], akey, sname)

        # Новая запись, о которой бот ещё не сообщил тренеру (notified_at пуст): мама Вари
        # записала дочь на индивидуальное к группе. Это кадр «уведомление тренеру».
        nd, nst = mon + timedelta(weeks=1, days=5), time(10, 0)
        nsl = add_slot(nd, nst, TRAINER["session_duration_minutes"], "zamok", SRV_ZERO, status="booked")
        nb = add_booking(nsl, "varya", SRV_ZERO, "zamok", nd, nst, status="pending",
                         comment="Варя ходит к вам в группу — хотим добавить индивидуальные")
        s.execute(text("UPDATE bookings SET notified_at = NULL, created_at = :cr WHERE id = :b"),
                  {"b": nb, "cr": now_utc - timedelta(minutes=4)})

        # Бот-сессии аккаунтов: пришли по ссылке тренера (как /start client_…_<trainer_id>).
        for key in cid:
            s.execute(
                text(
                    "INSERT INTO client_sessions (telegram_id, state, city_id, selected_trainer_id, "
                    "selected_arena_id) VALUES (:tg, 'idle', :city, :t, :a)"
                ),
                # Мама Софии выбирала «Замок» — там у дочери постоянные занятия.
                {"tg": tg_of[key], "city": city, "t": tid, "a": arena["zamok"] if key == "sofia" else None},
            )

        # --- связи клиент↔тренер (их создаёт запись; по ним родитель открывает тренера вне каталога) ---
        for key, client_id in cid.items():
            s.execute(
                text(
                    """
                    INSERT INTO client_trainer_edges (telegram_id, client_id, trainer_id, is_saved, is_primary,
                        completed_count, last_booking_at, last_completed_at, last_interaction_at,
                        last_booking_service_id)
                    SELECT :tg, :c, :t, true, true,
                           COUNT(*) FILTER (WHERE b.status = 'completed'),
                           MAX(b.created_at),
                           MAX(s.slot_date + s.start_time) FILTER (WHERE b.status = 'completed'),
                           MAX(b.created_at),
                           (ARRAY_AGG(b.service_id ORDER BY b.created_at DESC))[1]
                    FROM bookings b JOIN slots s ON s.id = b.slot_id
                    WHERE b.client_id = :c AND b.trainer_id = :t
                    """
                ),
                {"tg": tg_of[key], "c": client_id, "t": tid},
            )

        # --- абонемент «5 из 8» у Софии: 3 последних занятия списаны ---------------------------
        pname, total, pprice, valid = PASS_PRODUCT
        pp = _id(
            s,
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, validity_days)
            VALUES (:t, :n, :k, :p, :v) RETURNING id
            """,
            t=tid, n=pname, k=total, p=pprice * 100, v=valid,
        )
        for sname in (SRV_FIGURE, SRV_IMPROVE):
            s.execute(text("INSERT INTO trainer_pass_product_services (pass_product_id, service_id) VALUES (:p, :s)"),
                      {"p": pp, "s": srv[sname]})
        used = sofia_done[-3:]
        issued = now_utc - timedelta(days=12)
        pi = _id(
            s,
            """
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, issued_at,
                                        expires_at, status, price_cents)
            VALUES (:c, :p, :r, :k, :i, :e, 'active', :pr) RETURNING id
            """,
            c=cid["sofia"], p=pp, r=total - len(used), k=total, i=issued, e=issued + timedelta(days=valid),
            pr=pprice * 100,
        )
        for b in used:
            s.execute(text("INSERT INTO pass_redemptions (booking_id, pass_instance_id) VALUES (:b, :p)"),
                      {"b": b, "p": pi})

        print(f"demo trainer id={tid} tg={DEMO_TRAINER_TG} week from {mon}; clients={cid}; pass={pi}")


if __name__ == "__main__":
    main()
