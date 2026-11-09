"""St. Petersburg rink cards, batch 3: Yubileyny, Dinamo-Yunior, Izhorets and Iceburg Arena (rinks with a parser).

Facts are taken from each rink's own site on 2026-11-09 (Izhorets prices: the rink price list PDF
approved 17.08.2026); sources and anything left out are in ``data/arena-cards/ru/spb-*.md``.
Unknown stays unset. Same write rules as 0311: text, phone and site replace the import; socials,
amenities, visit_info and visit_info.facts are merged.

Revision ID: 0314_spb_rink_cards_batch3
Revises: 0313_spb_rink_cards_batch2
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0314_spb_rink_cards_batch3"
down_revision = "0313_spb_rink_cards_batch2"
branch_labels = None
depends_on = None

CARDS: dict[int, dict] = {
    97: {
        "name": "СК «Юбилейный»",
        "phone": "+7 (812) 507-11-11",
        "website_url": "https://www.yubi.ru/rink/",
        "social_urls": {"telegram": "https://t.me/yubileny_ru"},
        "short_description": (
            "СК «Юбилейный» на пр. Добролюбова, 18 (м. «Спортивная») продаёт часовые сеансы «Тренировка на льду» "
            "в онлайн-кассе на yubi.ru: 60 минут, 800 ₽. Проката коньков нет — приходите со своими. Билеты не "
            "обмениваются и не возвращаются, кроме отмены сеанса площадкой. Переодеваться — в раздевалках на "
            "1 этаже, в фойе детей переодевать нельзя."
        ),
        "amenities": {"locker_rooms": True},
        "visit_info": {
            "tickets": {"mode": "online", "note": "касса на yubi.ru/rink, обмену и возврату не подлежат"},
            "facts": {"locker_rooms": {"state": "yes", "note": "на 1 этаже"}},
            "custom_facts": [
                {"icon": "info", "title": "Проката коньков нет", "note": "только со своими коньками"},
                {
                    "icon": "info",
                    "title": "Входы",
                    "note": "главная арена — дверь №1, малая — №62, тренировочный каток — №55",
                },
            ],
        },
    },
    173: {
        "name": "Ледовая арена Динамо-Юниор",
        "phone": "+7 (812) 246-92-12",
        "website_url": "https://shorspb.ru/Skating",
        "short_description": (
            "Ледовая арена спортшколы олимпийского резерва по хоккею «Динамо-юниор» на ул. Фаворского, 7. "
            "Массовое катание — раз в неделю, по субботам 21:00–22:00: билет 500 ₽ за час, прокат коньков "
            "300 ₽ за пару на час. Оплата только безналичная, мест ограниченное количество. Заточки коньков и "
            "камеры хранения нет."
        ),
        "amenities": {"skate_rental": True},
        "visit_info": {
            "tickets": {"mode": "box_office", "note": "только безналичная оплата, мест ограниченно"},
            "facts": {"lockers": {"state": "no", "note": ""}},
            "custom_facts": [
                {"icon": "info", "title": "Заточки коньков нет", "note": ""},
                {"icon": "clock", "title": "Катание только по субботам", "note": "21:00–22:00"},
            ],
            "services": [{"kind": "rental", "price": "300 ₽", "note": "пара на 1 час"}],
        },
    },
    185: {
        "name": "Ижорец",
        "phone": "+7 (812) 645-75-33",
        "website_url": "https://izhorets.ru/objects/fok-izhorets/",
        "social_urls": {"telegram": "https://t.me/sokizhorets"},
        "short_description": (
            "Ледовая арена ФОК «Ижорец» в Металлострое (Пушкинская ул., 3А): массовое катание, «час хоккея» и "
            "спортивно-массовое катание для фигуристов. Билет на час: взрослым 500 ₽, детям от 7 лет 370 ₽, "
            "детям до 7 лет и пенсионерам 250 ₽. Прокат коньков 400 ₽/час, «помощник фигуриста» 160 ₽/час, "
            "заточка 500 ₽. Расписание сеансов уточняйте у администратора."
        ),
        "amenities": {"skate_rental": True, "skate_sharpening": True},
        "visit_info": {
            "tickets": {"mode": "box_office", "note": "льготы — по документу"},
            "custom_facts": [
                {"icon": "info", "title": "Дети до 10 лет — со взрослым", "note": "взрослый тоже оплачивает катание"},
                {"icon": "clock", "title": "Расписание — у администратора", "note": "+7 (812) 645-75-33"},
            ],
            "services": [
                {
                    "kind": "rental",
                    "price": "400 ₽/час",
                    "note": "нужен паспорт или другой документ; опоздание с возвратом больше 15 мин — оплата следующего часа",
                },
                {"kind": "aid", "price": "160 ₽/час", "note": "пингвин, медведь и пр."},
                {"kind": "sharpening", "price": "500 ₽", "note": ""},
                {
                    "kind": "other",
                    "label": "«Час хоккея»",
                    "price": "580 ₽/час",
                    "note": "только в полной экипировке; абонемент от 8 занятий — 500 ₽/час",
                },
            ],
        },
    },
    193: {
        "name": "Айсбург Арена",
        "phone": "+7 (812) 330-33-33",
        "website_url": "https://iceburgarena.ru/",
        "social_urls": {"vk": "https://vk.ru/iceburgarena"},
        "short_description": (
            "ICEBURG ARENA на Парашютной, 11 — спортцентр 2023 года (5031 м²) с полноразмерной крытой ледовой "
            "ареной, 13 раздевалками и итальянским рестораном с видом на лёд. Массовое катание: будни 800 ₽ за "
            "60 мин или 900 ₽ за 75 мин, выходные и праздники 900 ₽, ночное 800 ₽. Прокат 500 ₽ (залог 1000 ₽ "
            "или документ). На льду не больше 150 человек."
        ),
        "amenities": {"skate_rental": True, "locker_rooms": True, "cafe": True},
        "visit_info": {
            "tickets": {"mode": "online", "note": "онлайн на сайте или у администратора"},
            "facts": {
                "locker_rooms": {"state": "yes", "note": "13, из них 2 комфорт-класса"},
                "cafe": {"state": "yes", "note": "итальянский ресторан с видом на лёд"},
            },
            "custom_facts": [
                {"icon": "info", "title": "Без клюшек и прыжков", "note": "движение против часовой стрелки"},
                {"icon": "clock", "title": "Работает ежедневно", "note": "06:00–24:00"},
            ],
            "services": [
                {"kind": "rental", "price": "500 ₽", "note": "залог 1000 ₽ или документ (кроме паспорта)"},
                {
                    "kind": "other",
                    "label": "Льготный билет",
                    "price": "600 ₽",
                    "note": "многодетным, детям без попечения, участникам СВО, инвалидам — по документу",
                },
                {"kind": "other", "label": "«Час хоккея»", "price": "800–900 ₽", "note": "будни / выходные"},
                {
                    "kind": "other",
                    "label": "«Час фигурного катания»",
                    "price": "800–900 ₽",
                    "note": "будни 60 мин 800 ₽, 75 мин 900 ₽; выходные 900 ₽",
                },
            ],
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
