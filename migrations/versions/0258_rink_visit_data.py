"""Rink card v2: visit_info for Mogilev, Orsha, Ostrovets, Pinsk, Soligorsk, Lida and led.by.

Data the owner collected by phone and from the rinks' price lists (2026-10-22).
Left out on purpose: hockey lessons, synthetic ice, roller rental (not public skating),
and anything the source marked as a guess (warmth in Ostrovets).

Revision ID: 0258_rink_visit_data
Revises: 0257_arena_visit_info
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0258_rink_visit_data"
down_revision = "0257_arena_visit_info"
branch_labels = None
depends_on = None

VISIT: dict[int, dict] = {
    # Дворец спорта «Могилёв»: онлайн продают только вход.
    43: {
        "tickets": {"mode": "online", "desk_only_services": True},
        "services": [{"kind": "sharpening", "price": "8 BYN", "note": "пара коньков"}],
        "rink_rental": {"rows": [{"label": "Весь лёд", "minutes": 60, "price": "480 BYN"}]},
    },
    # Орша: время меняется, уточняют по телефону.
    31: {
        "facts": {"spectators": {"state": "yes", "price": "1 BYN", "note": "посмотреть катание с трибуны"}},
        "custom_facts": [
            {"icon": "clock", "title": "Время меняется", "note": "дни и часы уточняйте по телефону +375 216 44-30-44"}
        ],
        "services": [
            {"kind": "aid", "price": "5 BYN", "note": "держаться, пока учитесь стоять"},
            {"kind": "sharpening", "price": "8 BYN", "note": "абонемент: 4 пары — 25 BYN, 8 пар — 40 BYN"},
            {"kind": "protection", "price": "3 BYN за час", "note": "30 минут — 1,50 BYN"},
        ],
        "passes": {
            "columns": ["Свои коньки", "С прокатом"],
            "rows": [
                {"label": "4", "values": ["24 BYN", "38 BYN"]},
                {"label": "8", "values": ["48 BYN", "72 BYN"]},
                {"label": "12", "values": ["70 BYN", "96 BYN"]},
            ],
        },
    },
    # Островец.
    41: {
        "facts": {"locker_rooms": {"state": "yes", "note": "переобуться и оставить обувь"}},
        "rental": {
            "sizes": "26–47",
            "deposit": "документ, удостоверяющий личность; паспорт, вид на жительство и удостоверение беженца не подходят",
        },
        "services": [
            {"kind": "aid", "price": "1 BYN", "note": "держаться, пока учитесь стоять"},
            {"kind": "protection", "price": "3 BYN"},
            {"kind": "helmet", "price": "1 BYN"},
            {"kind": "sharpening", "price": "10 BYN", "note": "пара коньков"},
        ],
        "school": {
            "age_from": 4,
            "phone": "+375 44 775-49-92",
            "contact": "Елизавета Малиновская",
            "rows": [
                {"label": "Занятие, 15 минут", "child": "10 BYN", "adult": "15 BYN"},
                {"label": "Группа, 8 занятий", "child": "130 BYN", "adult": "144 BYN"},
            ],
        },
        "passes": {
            "columns": ["Детский", "Взрослый"],
            "rows": [
                {"label": "4", "values": ["15 BYN", "22 BYN"]},
                {"label": "8", "values": ["28 BYN", "43 BYN"]},
                {"label": "Безлимит, именной", "values": ["40 BYN", "61 BYN"]},
            ],
        },
        "rink_rental": {
            "rows": [
                {"label": "Только лёд", "minutes": 60, "price": "240 BYN"},
                {"label": "Лёд и раздевалка", "minutes": 60, "price": "265 BYN"},
                {"label": "Лёд, раздевалка и судейская", "minutes": 60, "price": "280 BYN"},
            ]
        },
    },
    # Пинск, «Волна».
    24: {
        "services": [
            {"kind": "rental", "price": "4,20 BYN"},
            {"kind": "sharpening", "price": "4,50 BYN", "note": "пара коньков"},
        ],
        "passes": {
            "columns": ["Детский", "Взрослый"],
            "rows": [
                {"label": "4", "values": ["16,72 BYN", "17,60 BYN"]},
                {"label": "8", "values": ["33,44 BYN", "35,20 BYN"]},
            ],
        },
        "rink_rental": {
            "rows": [
                {"label": "Открытый хоккей, до 7 человек", "minutes": 45, "price": "250 BYN"},
                {"label": "Хоккей вечером и ночью, любительские команды", "minutes": 90, "price": "280 BYN"},
            ]
        },
    },
    # Солигорск: онлайн-касса продаёт только на сегодняшние сеансы.
    19: {"tickets": {"mode": "same_day"}},
    # Ледовый дворец Минской области (led.by): онлайн — только в день сеанса.
    5: {"tickets": {"mode": "same_day"}},
    # Лида: касса в день катания и за два дня, онлайна нет (0256 положил то же в opening_hours).
    37: {
        "tickets": {"mode": "box_office", "open": "12:30", "close": "21:00", "presale_days": 2},
        "child_age_max": 16,
        "services": [
            {"kind": "rental", "label": "Прокат коньков, детский", "price": "5 BYN", "note": "до 16 лет; взрослый — 6 BYN"},
            {"kind": "sharpening", "price": "12 BYN", "note": "за пару; учащимся школы — бесплатно"},
            {"kind": "other", "label": "Заточка с мелким ремонтом", "price": "15 BYN", "note": "за пару"},
        ],
        "passes": {
            "columns": ["Детский", "Взрослый"],
            "rows": [{"label": "12", "values": ["73,50 BYN", "94,50 BYN"]}],
        },
    },
}

# Онлайн-касса led.by — если в профиле ссылки ещё нет.
LEDBY_TICKETS_URL = "https://led.by/tickets_online/"


def upgrade() -> None:
    bind = op.get_bind()
    for arena_id, data in VISIT.items():
        bind.execute(
            sa.text(
                "UPDATE arena_profiles SET visit_info = COALESCE(visit_info, '{}'::jsonb) || CAST(:v AS jsonb) "
                "WHERE arena_id = :a"
            ),
            {"v": json.dumps(data, ensure_ascii=False), "a": arena_id},
        )
    bind.execute(
        sa.text("UPDATE arena_profiles SET tickets_url = :u WHERE arena_id = 5 AND COALESCE(tickets_url, '') = ''"),
        {"u": LEDBY_TICKETS_URL},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE arena_profiles SET tickets_url = NULL WHERE arena_id = 5 AND tickets_url = :u"),
        {"u": LEDBY_TICKETS_URL},
    )
    for arena_id, data in VISIT.items():
        expr = "visit_info" + "".join(f" - '{key}'" for key in data)
        bind.execute(sa.text(f"UPDATE arena_profiles SET visit_info = {expr} WHERE arena_id = :a"), {"a": arena_id})
