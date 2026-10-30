"""Конькобежный стадион МКСК — отдельная площадка от хоккейной Минск Арены (arena 2)."""

ARENA_ID = 115
SLUG = "konkobezhnaya-arena"
NAME = "Конькобежный стадион"
ADDRESS = "проспект Победителей, 111"
LATITUDE = 53.935930
LONGITUDE = 27.481638
WEBSITE_URL = "https://minskarena.by/page.html?slug=massovie-katania"
PHONE = "+375447808501"
PARSER_KEY = "minskarena_speed_oval_v1"

HALL_TRACK = "Конькобежная дорожка"
HALL_HOCKEY = "Хоккейная площадка"
FORMAT_DISCO = "Дискотека на льду"


def speed_oval_hall(name: str | None) -> str | None:
    """Где на стадионе идёт массовое катание — по названию услуги ABWS.

    «Массовое катание на конькобежной дорожке» → «Конькобежная дорожка»;
    «… (хоккейная площадка на конькобежной арене)» → «Хоккейная площадка»;
    дискотека — формат, а не площадка: «Хоккейная площадка · дискотека на льду», а если площадка
    в названии не указана — просто «Дискотека на льду». Не узнали — None (поле пустое).
    """
    low = str(name or "").casefold()
    if not low:
        return None
    area = None
    if "хоккейн" in low:
        area = HALL_HOCKEY
    elif "дорожк" in low or "конькобежн" in low:
        area = HALL_TRACK
    if "дискотек" in low:
        return f"{area} · дискотека на льду" if area else FORMAT_DISCO
    return area
