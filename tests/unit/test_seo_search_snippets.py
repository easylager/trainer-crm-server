"""Сниппет в выдаче: заголовок под запрос, описание без дат и счётчиков, крошки."""

import json
import re
from datetime import date

from src.application.city_hub_page import (
    city_hub_description,
    city_hub_document_title,
    city_hub_search_description,
)
from src.application.place_links import breadcrumb_script
from src.application.place_page import og_description, search_description
from src.shared.city_locative import city_locative


def _hub(**extra):
    view = {
        "city": {"id": 1, "name": "Минск"},
        "rink_count": 5,
        "service_count": 3,
        "ohm_counts": {"all": 0},
        "skate_counts": {"all": 131},
        "skate_by_arena": {1: 40, 2: 70, 3: 21},
        "places": [
            {"id": 1, "name": "Чижовка-арена", "venue_type": "ice"},
            {"id": 2, "name": "ТЦ Замок", "venue_type": "ice"},
            {"id": 3, "name": "ТЦ DiaMond city", "venue_type": "ice"},
            {"id": 4, "name": "Пустой", "venue_type": "ice"},
            {"id": 5, "name": "Открытый", "venue_type": "outdoor"},
            {"id": 6, "name": "Заточка", "venue_type": "shop"},
        ],
        "place_count": 6,
    }
    view.update(extra)
    return view


def test_locative_covers_tricky_names_and_falls_back_to_none() -> None:
    assert city_locative("Гродно") == "Гродно"
    assert city_locative("Могилев") == "Могилёве"
    assert city_locative("Лунинец") == "Лунинце"
    assert city_locative("Неизвестноград") is None


def test_city_title_matches_the_search_query() -> None:
    assert city_hub_document_title(_hub()) == "Массовое катание в Минске — расписание катков | Glideclub"


def test_city_title_without_sessions_keeps_the_sections() -> None:
    assert city_hub_document_title(_hub(skate_counts={"all": 0})) == "Катки в Минске — массовое катание и расписание | Glideclub"


def test_catalog_home_snippet_leads_with_mass_skating_keyword() -> None:
    from src.application.catalog_home_page import catalog_home_document_title, catalog_home_search_description

    assert catalog_home_document_title().startswith("Массовое катание")
    text = catalog_home_search_description(
        [
            {"country": "BY", "name": "Минск"},
            {"country": "BY", "name": "Брест"},
            {"country": "BY", "name": "Гомель"},
            {"country": "BY", "name": "Витебск"},
        ]
    ).replace("\u00a0", " ")
    assert text.startswith("Массовое катание:")
    assert "Минск, Брест, Гомель" in text
    assert "телефоны" in text


def test_catalog_home_seo_intro_links_city_hubs() -> None:
    from src.application.catalog_home_page import catalog_home_seo_intro_html

    html = catalog_home_seo_intro_html(
        [{"country": "BY", "name": "Минск", "slug": "minsk"}, {"country": "BY", "name": "Брест", "slug": "brest"}]
    )
    assert "Массовое катание в Беларуси" in html
    assert 'href="/c/minsk"' in html
    assert 'href="/c/brest"' in html


def test_city_search_description_has_no_session_counts() -> None:
    text = city_hub_search_description(_hub()).replace(" ", " ")
    assert text == (
        "Массовое катание в Минске: расписание сеансов на сегодня, завтра и выходные. "
        "ТЦ Замок, Чижовка-арена, ТЦ DiaMond city и ещё 2 катка — цены и адреса. "
        "Заточка коньков — 3 места."
    )
    assert "131" not in text
    # Превью мессенджера по-прежнему считает — та же строка, что в тексте шера.
    assert city_hub_description(_hub()) == "6 мест · 131 сеанс"


def _place_view(**extra):
    view = {
        "card": {
            "name": "ТЦ Замок",
            "venue_type": "ice",
            "city_name": "Минск",
            "district": "Центральный район",
            "address": "пр-т Победителей, 65",
        },
        "today": date(2026, 10, 14),
        "next_slot": {"local_date": date(2026, 10, 14), "starts_at_local": "17:15"},
        "focus": None,
    }
    view.update(extra)
    return view


def test_place_search_description_has_no_date_but_preview_still_does() -> None:
    from src.application.place_page import page_title

    text = search_description(_place_view())
    assert text.startswith("Расписание массового катания на неделю, цены и как добраться. ")
    assert page_title(_place_view()).startswith("Массовое катание — ")
    assert page_title(_place_view()).endswith("| Glideclub")
    assert "пр-т Победителей, 65" in text
    assert not re.search(r"\d{1,2}:\d{2}|окт", text)
    assert "17:15" in og_description(_place_view())


def test_breadcrumbs_are_absolute_or_absent() -> None:
    html = breadcrumb_script(
        "https://glideclub.by/p/minsk/zamok",
        [("Glideclub", "/"), ("Минск", "/c/minsk"), ("ТЦ Замок", "https://glideclub.by/p/minsk/zamok")],
    )
    data = json.loads(re.search(r">(.*)</script>", html).group(1))
    assert data["@type"] == "BreadcrumbList"
    assert [i["item"] for i in data["itemListElement"]] == [
        "https://glideclub.by/",
        "https://glideclub.by/c/minsk",
        "https://glideclub.by/p/minsk/zamok",
    ]
    assert breadcrumb_script("/p/minsk/zamok", [("Glide", "/")]) == ""


def test_city_search_description_names_ohm_when_the_city_has_it() -> None:
    text = city_hub_search_description(_hub(ohm_counts={"all": 19}, ohm_arena_count=4)).replace("\u00a0", " ")
    assert "Открытые тренировки с клюшкой (ОХМ) — на 4 катках." in text
    assert "ОХМ" not in city_hub_search_description(_hub())
