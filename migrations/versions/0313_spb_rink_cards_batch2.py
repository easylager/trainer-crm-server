"""St. Petersburg rink cards, batch 2: Grand Canyon Ice, Bugry and Parnas (rinks with a parser).

Facts are taken from each rink's own site on 2026-11-09; sources and anything left out are in
``data/arena-cards/ru/spb-*.md``. Unknown stays unset. Same write rules as 0311: text, phone and
site replace the import; socials, amenities, visit_info and visit_info.facts are merged.

Revision ID: 0313_spb_rink_cards_batch2
Revises: 0312_ice_sessions_open_window
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0313_spb_rink_cards_batch2"
down_revision = "0312_ice_sessions_open_window"
branch_labels = None
depends_on = None

CARDS: dict[int, dict] = {
    # ЛД «Гранд Каньон Айс», grand-ice.ru
    99: {
        "name": "ЛД «Гранд Каньон Айс»",
        "phone": "+7 (812) 332-23-22",
        "website_url": "https://grand-ice.ru/",
        "social_urls": {"vk": "https://vk.com/grandcanyonice", "telegram": "https://t.me/GrandCanionIce"},
        "short_description": (
            "Ледовая арена «Гранд Каньон» на Суздальском пр., 29: поле 61×30, 10 минут пешком "
            "от «Проспекта Просвещения». Сеанс — час: в будни 700 ₽, в выходные и праздники 800 ₽, "
            "детям до 6 лет 500 ₽. Прокат фигурных и хоккейных коньков 500 ₽, «помощник фигуриста» "
            "200 ₽. Раздевалки с душем, кафе, 2 часа парковки бесплатно. Открыто с 7:00 до 0:00."
        ),
        "amenities": {"skate_rental": True, "cafe": True, "parking": True, "locker_rooms": True},
        "visit_info": {
            "tickets": {"mode": "box_office", "note": "билет на сеанс и прокат — в кассе арены"},
            "facts": {
                "locker_rooms": {"state": "yes", "note": "просторные, с душевыми"},
                "cafe": {"state": "yes", "note": ""},
                "parking": {"state": "yes", "note": "2 часа бесплатно, дальше 100 ₽ в час, въезд с Суздальского"},
            },
            "custom_facts": [
                {"icon": "child", "title": "Дети до 7 лет — со взрослым", "note": "держать детей на руках нельзя"},
                {"icon": "card", "title": "Детский билет — до 6 лет", "note": "по документу о возрасте"},
                {
                    "icon": "person",
                    "title": "Не больше 300 человек",
                    "note": "при заполнении продажу билетов приостанавливают",
                },
            ],
            "services": [
                {
                    "kind": "aid",
                    "label": "«Помощник фигуриста»",
                    "price": "200 ₽",
                    "note": "за час, размеры для детей и взрослых",
                },
                {"kind": "rental", "price": "500 ₽", "note": "за час; залог 1500 ₽ наличными или документ"},
            ],
            "rental": {"sizes": "29–48"},
            "rink_rental": {
                "phone": "+7 (921) 773-02-10",
                "rows": [{"label": "Поле 61×30, тренировки и мероприятия", "minutes": 60, "price": "по запросу"}],
            },
        },
    },
    # Ледовая арена «Бугры», spb-katok.ru
    111: {
        "name": "Ледовая арена Бугры",
        "phone": "+7 (921) 317-93-47",
        "website_url": "https://spb-katok.ru/",
        "short_description": (
            "Крытый каток в Буграх рядом с Девяткино: Большая арена на Шоссейной, 42 и Малая — "
            "на Шоссейной, 31. Массовое катание по расписанию на Большой арене, каждый день, "
            "билет 600 ₽, прокат коньков 500 ₽. Там же час хоккея за 600 ₽, аренда льда, "
            "школы фигурного катания «Чемпион», «Локомотив», «Вымпел» и детский хоккей."
        ),
        "amenities": {"skate_rental": True},
        "visit_info": {
            "services": [
                {"kind": "rental", "price": "500 ₽", "note": "на сеанс"},
                {"kind": "other", "label": "Час хоккея", "price": "600 ₽", "note": "на Большой и Малой арене"},
            ],
            "rink_rental": {
                "phone": "+7 (921) 317-93-47",
                "rows": [
                    {"label": "Большая арена", "minutes": 60, "price": "14 000 ₽"},
                    {"label": "Большая арена, будни 16:00–22:00", "minutes": 60, "price": "17 000 ₽"},
                    {"label": "Малая арена, будни", "minutes": 60, "price": "8 000–12 000 ₽"},
                    {"label": "Малая арена, сб–вс", "minutes": 60, "price": "12 000 ₽"},
                ],
            },
        },
    },
    # Центр ледовых видов спорта «Парнас», parnas-arena.ru
    174: {
        "name": "Центр ледовых видов спорта Парнас",
        "phone": "+7 (911) 926-20-99",
        "website_url": "https://parnas-arena.ru/",
        "social_urls": {"vk": "https://vk.com/parnas_center", "telegram": "https://t.me/parnascenter"},
        "short_description": (
            "Круглогодичный крытый каток на Парнасе, 6-й Верхний пер., 12Б: лёд 1000 м², тёплые "
            "раздевалки с душем, кафе и большая бесплатная парковка. Массовое катание — 700 ₽ "
            "за сеанс для взрослых и детей, ледовая дискотека — 800 ₽, абонемент на 10 посещений "
            "5500 ₽. Прокат 500 ₽, заточка от 500 ₽. Клюшки и шайбы — только на часе хоккея."
        ),
        "amenities": {
            "skate_rental": True,
            "skate_sharpening": True,
            "cafe": True,
            "parking": True,
            "locker_rooms": True,
        },
        "visit_info": {
            "tickets": {"mode": "box_office", "note": "оплата до начала сеанса при входе в арену"},
            "facts": {
                "locker_rooms": {"state": "yes", "note": "тёплые, с душевыми"},
                "cafe": {"state": "yes", "note": ""},
                "parking": {"state": "yes", "note": "большая бесплатная"},
            },
            "custom_facts": [
                {"icon": "info", "title": "Без клюшек и шайб", "note": "хоккей — на «часе хоккея», по записи"},
                {"icon": "clock", "title": "Сеансы могут меняться", "note": "уточняйте: +7 (911) 926-20-99"},
            ],
            "services": [
                {"kind": "rental", "price": "500 ₽", "note": "за сеанс, нужен залог — сумму уточняйте в кассе"},
                {"kind": "sharpening", "price": "от 500 ₽", "note": "вт, чт 15:00–21:00, сб 9:00–15:00"},
                {
                    "kind": "other",
                    "label": "«Час хоккея»",
                    "price": "700 ₽",
                    "note": "запись по телефону, только в полной амуниции",
                },
                {
                    "kind": "other",
                    "label": "Тренировка с инструктором",
                    "price": "3 900 ₽",
                    "note": "2500 ₽ инструктор + 1400 ₽ выход на лёд",
                },
            ],
            "passes": {
                "columns": ["Цена", "Срок"],
                "rows": [
                    {"label": "5", "values": ["3 000 ₽", "1 месяц"]},
                    {"label": "10", "values": ["5 500 ₽", "1 месяц"]},
                    {"label": "20", "values": ["10 400 ₽", "2 месяца"]},
                ],
            },
            "rink_rental": {
                "phone": "+7 (911) 926-20-99",
                "rows": [
                    {"label": "Будни, утро и день", "minutes": 60, "price": "5 000–14 000 ₽"},
                    {"label": "Будни, вечер 21:30–23:00", "price": "14 000 ₽"},
                    {"label": "Выходные", "price": "8 000–18 000 ₽"},
                ],
            },
        },
    },
}


def _profile_sql(card: dict) -> tuple[str, dict]:
    sets = [
        "phone = :phone",
        "website_url = :site",
        "short_description = :descr",
        "social_urls = COALESCE(social_urls, '{}'::jsonb) || CAST(:socials AS jsonb)",
        "amenities = COALESCE(amenities, '{}'::jsonb) || CAST(:amenities AS jsonb)",
        "visit_info = COALESCE(visit_info, '{}'::jsonb) || CAST(:visit AS jsonb)"
        + (
            # Факты дополняют уже собранные (раздевалка с прода), а не затирают их.
            " || jsonb_build_object('facts', COALESCE(visit_info->'facts', '{}'::jsonb)"
            " || (CAST(:visit AS jsonb)->'facts'))"
            if "facts" in card["visit_info"]
            else ""
        ),
        "updated_at = now()",
    ]
    params = {
        "phone": card["phone"],
        "site": card["website_url"],
        "descr": card["short_description"],
        "socials": json.dumps(card.get("social_urls") or {}, ensure_ascii=False),
        "amenities": json.dumps(card.get("amenities") or {}),
        "visit": json.dumps(card["visit_info"], ensure_ascii=False),
    }
    return ", ".join(sets), params


def upgrade() -> None:
    bind = op.get_bind()
    for arena_id, card in CARDS.items():
        # Ид арены на проде и локально совпадают (capital_arenas); имя страхует от чужой арены.
        found = bind.execute(
            sa.text("SELECT 1 FROM arenas WHERE id = :a AND name = :n"), {"a": arena_id, "n": card["name"]}
        ).first()
        if found is None:
            continue
        sets, params = _profile_sql(card)
        bind.execute(sa.text(f"UPDATE arena_profiles SET {sets} WHERE arena_id = :a"), {**params, "a": arena_id})
        if card.get("address"):
            bind.execute(
                sa.text("UPDATE arenas SET address = :addr WHERE id = :a"), {"addr": card["address"], "a": arena_id}
            )


def downgrade() -> None:
    bind = op.get_bind()
    for arena_id, card in CARDS.items():
        visit = "visit_info" + "".join(f" - '{key}'" for key in card["visit_info"])
        amen = "amenities" + "".join(f" - '{key}'" for key in card.get("amenities") or {})
        bind.execute(
            sa.text(f"UPDATE arena_profiles SET visit_info = {visit}, amenities = {amen} WHERE arena_id = :a"),
            {"a": arena_id},
        )
