"""St. Petersburg rink cards, batch 1: seven rinks that already have a schedule parser.

Ozerki, Ice Palace (pr. Pyatiletok), Kupchino, Shans Arena, Magnit Arena, Baltic Arena and
Shuvalovsky Lyod. Facts are taken from each rink's own site on 2026-11-09; sources and
anything left out are in ``data/arena-cards/ru/spb-*.md``. Unknown stays unset.

The card text, phone and site replace what the import left; socials, amenities, visit_info
and visit_info.facts are merged. Downgrade removes the visit_info keys and amenities this migration
set; the old text, phone and site are not restored (the import kept none worth keeping).

Revision ID: 0313_spb_rink_cards_batch1
Revises: 0312_kk_promo_src
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0313_spb_rink_cards_batch1"
down_revision = "0312_kk_promo_src"
branch_labels = None
depends_on = None

CARDS: dict[int, dict] = {
    # Ледовая арена «Озерки», katok-ozerki.ru
    101: {
        "name": "Ледовая арена Озерки",
        "phone": "+7 (812) 929-49-79",
        "website_url": "https://katok-ozerki.ru/",
        "social_urls": {"vk": "https://vk.com/katokozerki"},
        "short_description": (
            "Ледовая арена у метро «Озерки»: четыре площадки — Большая и Центральная 26×56, "
            "тренировочная 26×50 и Малая 20×40, бросковая зона и игровой зал. Свободное катание "
            "и «час хоккея» без записи — приходите к началу сеанса. Проката коньков нет, "
            "берите свои; заточка и ремонт — в сервисном центре арены."
        ),
        "amenities": {"skate_rental": False, "skate_sharpening": True, "parking": True},
        "visit_info": {
            "tickets": {"mode": "box_office", "note": "без бронирования, вход на сеанс у администратора"},
            "facts": {"parking": {"state": "yes", "note": ""}},
            "custom_facts": [
                {"icon": "info", "title": "Проката коньков нет", "note": "приходите со своими коньками"},
                {
                    "icon": "ruler",
                    "title": "Цена зависит от площадки",
                    "note": "Большая и Центральная — 500 ₽, Малая — 400 ₽ за сеанс",
                },
            ],
            "services": [
                {"kind": "sharpening", "price": "", "note": "сервисный центр: +7 (931) 233-83-84"},
                {
                    "kind": "other",
                    "label": "«Час хоккея»",
                    "price": "600 ₽",
                    "note": "на Малой арене — 500 ₽, без бронирования",
                },
            ],
            "rink_rental": {
                "phone": "+7 (812) 929-49-79",
                "rows": [
                    {"label": "Большая арена, утро и будни до 14:00", "minutes": 60, "price": "8 000 ₽"},
                    {"label": "Большая арена, вечер и выходные", "minutes": 60, "price": "12 500 ₽"},
                    {"label": "Малая арена", "minutes": 60, "price": "от 6 000 ₽"},
                ],
            },
        },
    },
    # Ледовый дворец, newarena.spb.ru/rink/
    105: {
        "name": "Ледовый дворец",
        "phone": "+7 (812) 718-44-76",
        "website_url": "https://newarena.spb.ru/rink/",
        "short_description": (
            "Каток Ледового дворца на проспекте Пятилеток, 1 — арены, где проходят концерты и "
            "матчи. Сеанс длится час: днём с 10:00 до 17:15 взрослый билет 600 ₽, вечером "
            "с 17:30 — 700 ₽, детям до 7 лет 400 и 450 ₽. Билеты онлайн или по QR-коду при "
            "входе. В дни концертов каток не работает — смотрите расписание."
        ),
        "amenities": {"skate_rental": True, "parking": True},
        "visit_info": {
            "tickets": {"mode": "online", "note": "можно купить заранее на сайте или по QR-коду у входа на каток"},
            "facts": {
                "parking": {
                    "state": "yes",
                    "note": "платная: первые 15 минут бесплатно, дальше 100 ₽ в час; в дни мероприятий дороже",
                }
            },
            "custom_facts": [
                {"icon": "child", "title": "Дети до 10 лет — со взрослым", "note": "одних на лёд не пускают"},
                {
                    "icon": "clock",
                    "title": "Работает не каждый день",
                    "note": "в дни концертов и матчей катка нет; по расписанию: +7 (921) 855-23-79",
                },
            ],
            "services": [
                {"kind": "rental", "label": "Прокат коньков, взрослый", "price": "450 ₽", "note": "за час"},
                {"kind": "rental", "label": "Прокат коньков, детям до 7 лет", "price": "300 ₽", "note": "за час"},
            ],
        },
    },
    # Ледовая арена «Купчино», arenakupchino.ru
    110: {
        "name": "Ледовая арена «Купчино»",
        "phone": "+7 (812) 903-57-63",
        "website_url": "https://arenakupchino.ru/",
        "social_urls": {"vk": "https://vk.com/arenakupchino"},
        "short_description": (
            "Крытая арена во Фрунзенском районе, ул. Димитрова, 3А: лёд 56×26, раздевалки "
            "с отдельным санузлом и панорамное кафе с видом на лёд. На массовом катании вход "
            "500 ₽, прокат хоккейных и фигурных коньков — 500 ₽. Здесь же заточка, детская "
            "хоккейная школа «Добрыня» с 3 лет и аренда льда. Открыто с 8:00 до 23:00."
        ),
        "amenities": {"skate_rental": True, "skate_sharpening": True, "cafe": True, "locker_rooms": True},
        "visit_info": {
            "facts": {
                "locker_rooms": {"state": "yes", "note": "в каждой раздевалке свой санузел"},
                "cafe": {"state": "yes", "note": "панорамное кафе с видом на лёд"},
            },
            "services": [
                {"kind": "rental", "price": "500 ₽", "note": "хоккейные и фигурные коньки на сеанс"},
                {"kind": "sharpening", "price": "от 500 ₽", "note": "вт–вс 10:00–21:00, +7 (931) 387-26-89"},
            ],
        },
    },
    # СК «Шанс Арена», shans-arena.ru
    100: {
        "name": "Ледовый комплекс «Шанс Арена»",
        "phone": "+7 (812) 777-11-77",
        "website_url": "https://shans-arena.ru/",
        "short_description": (
            "Спорткомплекс у метро «Лесная» (ул. Грибалёвой, 9к2, въезд с Кантемировской, 37) "
            "с крытой коробкой 56×26. Час свободного катания — 900 ₽ для взрослых и детей, "
            "прокат коньков 600 ₽, защита 200 ₽. Опора для новичков бесплатно, раздевалка "
            "входит в билет. Кроме катания — час хоккея, час фигурного катания, кафе и падел."
        ),
        "amenities": {
            "skate_rental": True,
            "skate_sharpening": True,
            "cafe": True,
            "parking": True,
            "locker_rooms": True,
        },
        "visit_info": {
            "facts": {
                "locker_rooms": {"state": "yes", "note": "входит в билет, есть питьевая вода"},
                "lockers": {"state": "yes", "note": "шкафчик 150 ₽ за час, 1500 ₽ в месяц"},
                "cafe": {"state": "yes", "note": ""},
                "parking": {"state": "yes", "note": ""},
            },
            "custom_facts": [
                {"icon": "card", "title": "2–11 января — 1000 ₽", "note": "праздничная цена на все часовые сеансы"},
            ],
            "services": [
                {"kind": "aid", "price": "бесплатно", "note": "держаться, пока учитесь стоять"},
                {"kind": "rental", "price": "600 ₽", "note": ""},
                {"kind": "protection", "price": "200 ₽", "note": "за элемент"},
                {
                    "kind": "other",
                    "label": "Тренер на катании",
                    "price": "3 300 ₽",
                    "note": "хоккей или фигурное, запись заранее",
                },
            ],
            "rental": {"deposit": "3000 ₽ за пару или комплект"},
        },
    },
    # «Магнит Арена», magnit-arena.ru
    187: {
        "name": "Ледовая арена Магнит",
        "phone": "+7 (921) 419-55-55",
        "website_url": "http://magnit-arena.ru/",
        "social_urls": {"telegram": "https://t.me/magnitarena"},
        "short_description": (
            "Два ледовых поля у метро «Ладожская», Магнитогорская, 51В. Массовое катание и час "
            "хоккея — 600 ₽ за сеанс, по утрам в будни часть сеансов по акции за 150 ₽. "
            "Абонемент на 10 посещений — 5000 ₽, на 20 — 9000 ₽. Прокат коньков 350 ₽, "
            "заточка 600 ₽. Занятия с тренером для детей и взрослых, работает круглый год."
        ),
        "amenities": {"skate_rental": True, "skate_sharpening": True},
        "visit_info": {
            "custom_facts": [
                {"icon": "card", "title": "Утром — 150 ₽", "note": "акция на отмеченные сеансы в будни"},
            ],
            "services": [
                {"kind": "rental", "price": "350 ₽", "note": "хоккейные и фигурные, за сеанс, отдельно от билета"},
                {"kind": "sharpening", "price": "600 ₽", "note": "за пару"},
            ],
            "passes": {
                "columns": ["Цена"],
                "rows": [
                    {"label": "10", "values": ["5 000 ₽"]},
                    {"label": "20", "values": ["9 000 ₽"]},
                ],
            },
            "rink_rental": {
                "phone": "+7 (921) 419-55-55",
                "rows": [{"label": "Весь лёд, по дню и времени", "minutes": 60, "price": "10 000–18 000 ₽"}],
            },
        },
    },
    # «Балтик Арена», baltic-arena.ru
    192: {
        "name": "Балтик Арена",
        "address": "проспект Крузенштерна, 18, стр. 1",
        "phone": "+7 (921) 911-71-41",
        "website_url": "https://baltic-arena.ru/",
        "social_urls": {"telegram": "https://t.me/balticarenaspb", "vk": "https://vk.ru/balticsrenaspb"},
        "short_description": (
            "Новая арена 2025 года на Васильевском острове, пр. Крузенштерна, 18, с кафе "
            "с видом на Финский залив. Массовое катание — 700 ₽ за 60 минут и 850 ₽ за 75, "
            "билет в кассе на ресепшене перед сеансом, без записи. «Пингвины» бесплатно, "
            "прокат 550 ₽, заточка 500 ₽. Открыто каждый день с 6:30 до полуночи."
        ),
        "amenities": {"skate_rental": True, "skate_sharpening": True, "cafe": True, "locker_rooms": True},
        "visit_info": {
            "tickets": {"mode": "box_office", "note": "касса на ресепшене, перед сеансом"},
            "facts": {
                "cafe": {"state": "yes", "note": "с видом на Финский залив"},
                "spectators": {"state": "yes", "price": "", "note": "трибуны чуть выше уровня льда"},
            },
            "services": [
                {"kind": "aid", "price": "бесплатно", "note": "опоры «пингвины» на массовом катании"},
                {"kind": "rental", "price": "550 ₽", "note": "за час"},
                {"kind": "sharpening", "price": "500 ₽", "note": ""},
            ],
            "rental": {"sizes": "36–45,5"},
            "rink_rental": {
                "phone": "+7 (921) 911-71-41",
                "rows": [
                    {"label": "1/3 льда на часе хоккея", "minutes": 60, "price": "6 000 ₽"},
                    {"label": "1/2 льда на часе хоккея", "minutes": 60, "price": "7 000 ₽"},
                ],
            },
        },
    },
    # «Шуваловский лёд», shuvalov-ice.ru
    196: {
        "name": "Шуваловский лёд",
        "phone": "+7 (812) 40-222-40",
        "website_url": "https://shuvalov-ice.ru/",
        "social_urls": {"telegram": "https://t.me/shuvalov_ice", "vk": "https://vk.com/shuvalov_ice"},
        "short_description": (
            "Ледовый комплекс на Лидии Зверевой, 8: две большие арены 60×28 и две малые 30×21. "
            "Массовое катание без записи — от 800 ₽ за час, длинные сеансы по 1 ч 15 мин "
            "дороже. Прокат 600 ₽ в час, заточка 500 ₽. Для новичков есть опоры, "
            "детям 3–14 лет — только со взрослым. Работает ежедневно с 6:00 до 1:00."
        ),
        "amenities": {"skate_rental": True, "skate_sharpening": True, "cafe": True, "parking": True},
        "visit_info": {
            "facts": {
                "lockers": {"state": "yes", "note": "в зоне проката можно оставить обувь"},
                "cafe": {"state": "yes", "note": ""},
                "parking": {"state": "yes", "note": "платная"},
            },
            "custom_facts": [
                {"icon": "child", "title": "3–14 лет — со взрослым", "note": "или с тренером"},
                {"icon": "person", "title": "На малых аренах до 25 человек", "note": ""},
            ],
            "services": [
                {"kind": "aid", "price": "", "note": "опоры для новичков"},
                {"kind": "rental", "price": "600 ₽", "note": "за час"},
                {"kind": "sharpening", "price": "500 ₽", "note": ""},
            ],
            "rental": {"sizes": "26–48"},
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
