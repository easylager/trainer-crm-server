"""Regional (non-Minsk) Belarus ice arenas used by the parser-job seed.

``parser_key`` is set only when ``scripts/seed_regional_ice_parser_jobs.py`` upserts a job.
Slug and city on that job come from this list, not from a second hand-written copy.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.ingestion.arena_seed import SeedArena, SeedCity, apply_arena_seed

# Cities beyond the ones a fresh database already gets from the capital seed.
NEW_CITIES: list[SeedCity] = [
    SeedCity("Барановичи", 10),
    SeedCity("Береза", 11),
    SeedCity("Бобруйск", 12),
    SeedCity("Брест", 13),
    SeedCity("Витебск", 14),
    SeedCity("Горки", 15),
    SeedCity("Гродно", 16),
    SeedCity("Жодино", 17),
    SeedCity("Ивацевичи", 18),
    SeedCity("Кобрин", 19),
    SeedCity("Лида", 20),
    SeedCity("Лунинец", 21),
    SeedCity("Могилёв", 22),
    SeedCity("Молодечно", 23),
    SeedCity("Новополоцк", 24),
    SeedCity("Орша", 25),
    SeedCity("Островец", 26),
    SeedCity("Пинск", 27),
    SeedCity("Пружаны", 28),
    SeedCity("Раубичи", 29),
    SeedCity("Силичи", 30),
    SeedCity("Солигорск", 31),
    SeedCity("Шклов", 32),
]

# arena ids match the prod census and the parser specs.
ARENAS: list[SeedArena] = [
    SeedArena(
        23,
        "Барановичи",
        "Ледовый дворец спорта",
        "Советский проспект, 20",
        53.1493182,
        26.0014462,
        "baranovichi-lds",
        True,
        "baranovichi_lds_v1",
    ),
    SeedArena(26, "Береза", "Ледовая арена", "ул. 17 Сентября, 39", 52.5299, 24.98099, "bereza-lds", False),
    SeedArena(
        38,
        "Бобруйск",
        "Бобруйск-арена",
        "Карбышева 11",
        53.1423013,
        29.2469144,
        "bobruisk-arena",
        True,
        "bobruisk_arena_v1",
    ),
    SeedArena(
        22,
        "Брест",
        "Брестский ледовый дворец спорта",
        "ул. Московская, 151",
        52.0926764,
        23.7384897,
        "brest-lds",
        True,
        "brest_lds_v1",
    ),
    SeedArena(
        29,
        "Витебск",
        "Дворец спорта",
        "проспект Строителей 23",
        55.1692254,
        30.2266233,
        "vitebsk-ds",
        True,
        "vitebsk_ds_v1",
    ),
    SeedArena(
        32, "Горки", "Ледовый дворец", "Вокзальная улица 23", 54.2747969, 30.9993037, "gorki-lds", True, "gorki_lds_v1"
    ),
    SeedArena(
        10,
        "Гродно",
        "ТЦ «Тринити»",
        "проспект Янки Купалы 87",
        53.649866,
        23.854538,
        "grodno-triniti",
        True,
        "grodno_triniti_v1",
    ),
    SeedArena(
        11,
        "Гродно",
        "Ледовый дворец спорта",
        "ул. Коммунальная 3а",
        53.68819,
        23.824166,
        "grodno-neman",
        True,
        "grodno_neman_v1",
    ),
    SeedArena(
        20,
        "Жодино",
        "Ледовая площадка ГУ СДЮШОР",
        "ул. Лебедевского, 18",
        54.0942605,
        28.3262757,
        "zhodino-sdyushor",
        False,
    ),
    SeedArena(28, "Ивацевичи", "Ледовая арена", "Спортивная 3", 52.7211098, 25.3303487, "ivatsevichi-lds", False),
    SeedArena(
        25,
        "Кобрин",
        "Ледовая арена",
        "Замковая площадь 11А",
        52.2136574,
        24.3641108,
        "kobrin-lds",
        True,
        "kobrin_lds_v1",
    ),
    SeedArena(37, "Лида", "Ледовый дворец", "Качана 31", 53.8954462, 25.3237632, "lida-lds", True, "lida_lds_v1"),
    SeedArena(40, "Лунинец", "СК Олимп-2011", "Красная улица 160Б", 52.2600712, 26.7899673, "luninets-olimp", False),
    SeedArena(
        43,
        "Могилёв",
        "Дворец спорта «Могилёв»",
        "ул. Гагарина 1",
        53.88464,
        30.32903,
        "mogilev-ds",
        True,
        "mogilev_ds_v1",
    ),
    SeedArena(
        18,
        "Молодечно",
        "Спортивно-развлекательный центр",
        "ул. Великий Гостинец, 102",
        54.3011204,
        26.8650159,
        "molodechno-src",
        False,
        "molodechno_src_v1",
    ),
    SeedArena(
        30,
        "Новополоцк",
        "Ледовый дворец",
        "ул. Молодёжная, 94Б",
        55.5069684,
        28.7024495,
        "novopolotsk-lds",
        True,
        "novopolotsk_lds_v1",
    ),
    SeedArena(
        31,
        "Орша",
        "Ледовая арена",
        "ул. Владимира Ленина, 79",
        54.5217761,
        30.4381153,
        "orsha-arena",
        True,
        "orsha_arena_v1",
    ),
    SeedArena(
        41,
        "Островец",
        "Ледовая площадка",
        "Октябрьская улица 39",
        54.6101379,
        25.9612152,
        "ostrovets-lds",
        True,
        "ostrovets_lds_v1",
    ),
    SeedArena(
        24,
        "Пинск",
        "Ледовая арена УСК «Волна»",
        "ул. Иркутско-Пинской дивизии, 46",
        52.1221795,
        26.1277244,
        "pinsk-volna",
        True,
        "pinsk_volna_v1",
    ),
    SeedArena(
        27,
        "Пружаны",
        "Ледовая арена ГУ СДЮШОР №2",
        "ул. Заводская, 15",
        52.5663378,
        24.4743121,
        "pruzhany-sdyushor",
        False,
    ),
    SeedArena(
        15,
        "Раубичи",
        "РЦОП по зимним видам спорта",
        "Минский район, Острошицко-Городской сельсовет",
        54.0628,
        27.7354,
        "raubichi-rcop",
        False,
    ),
    SeedArena(
        16,
        "Силичи",
        "Крытый каток РГЦ «Силичи»",
        "Минская обл., Логойский р-н, РГЦ «Силичи»",
        54.1565,
        27.8349,
        "silichi-rgc",
        False,
    ),
    SeedArena(
        19,
        "Солигорск",
        "Спортивно-зрелищный комплекс",
        "ул. К. Заслонова, 25",
        52.7909489,
        27.5366473,
        "soligorsk-szk",
        True,
        "soligorsk_szk_v1",
    ),
    SeedArena(
        42, "Шклов", "Ледовая арена", "ул. Почтовая 2", 54.2044194, 30.3049466, "shklov-arena", True, "shklov_arena_v1"
    ),
    SeedArena(
        33,
        "Гомель",
        "Гомельский ледовый дворец спорта",
        "ул. Мазурова, 110",
        52.4604315,
        31.0219016,
        "gomel-lds",
        True,
        "gomel_lds_v1",
    ),
]


def apply_regional_arenas(session: Session, *, verbose: bool = True) -> None:
    """Insert regional cities, arenas, and profiles. Does not commit."""
    cities = list(NEW_CITIES)
    known = {city.name for city in cities}
    for arena in ARENAS:
        if arena.city_name in known:
            continue
        cities.append(SeedCity(arena.city_name, 9))
        known.add(arena.city_name)
    apply_arena_seed(session, cities, ARENAS, verbose=verbose)
