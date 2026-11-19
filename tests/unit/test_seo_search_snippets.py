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
    assert city_hub_document_title(_hub()) == "Катки Минска — массовое катание и расписание | Glide"


def test_city_title_without_sessions_keeps_the_sections() -> None:
    assert city_hub_document_title(_hub(skate_counts={"all": 0})) == "Катки Минска — массовое катание и расписание | Glide"


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


def test_city_search_description_has_no_session_counts() -> None:
    text = city_hub_search_description(_hub()).replace(" ", " ")
    assert text == (
        "Где покататься на коньках в Минске: адреса катков, расписание массового катания и цены. "
        "Чижовка-арена, ТЦ Замок, ТЦ DiaMond city и ещё 2 катка. "
        "Заточка коньков — 3 места."
    )
    assert "131" not in text
    # Превью мессенджера по-прежнему считает — та же строка, что в тексте шера.
    assert city_hub_description(_hub()) == "6 мест · 131 сеанс"


def _place_view(**extra):
    view = {
        "session_count": 5,
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
    assert page_title(_place_view()) == "ТЦ Замок, Минск — каток, расписание массового катания | Glide"
    assert "пр-т Победителей, 65" in text
    assert not re.search(r"\d{1,2}:\d{2}|окт", text)
    assert "17:15" in og_description(_place_view())


def _view_in(city: str, **card):
    view = _place_view()
    view["card"] = {**view["card"], "city_name": city, **card}
    return view


def test_minsk_rink_title_only_for_minsk_with_schedule() -> None:
    from src.application.place_page import page_title

    # Регионы и места без публикуемого расписания остаются на прежнем шаблоне.
    for city in ("Молодечно", "Мозырь", "Берёза"):
        assert page_title(_view_in(city)) == f"Массовое катание — ТЦ Замок, {city} | Glide"
    for mode in ("phone", "season_closed"):
        assert page_title(_view_in("Минск", schedule_mode=mode)).startswith("Массовое катание — ")


def test_minsk_rink_without_sessions_keeps_old_title() -> None:
    from src.application.place_page import page_title

    view = _place_view(days=[], session_count=0)
    assert page_title(view).startswith("Массовое катание — ")


def test_minsk_ice_without_public_skate_keeps_own_title() -> None:
    from src.application.place_page import page_title

    title = page_title(_view_in("Минск", amenities={"hockey_center": True}))
    assert "расписание массового катания" not in title


def test_breadcrumbs_are_absolute_or_absent() -> None:
    html = breadcrumb_script(
        "https://glideclub.by/p/minsk/zamok",
        [("Glide", "/"), ("Минск", "/c/minsk"), ("ТЦ Замок", "https://glideclub.by/p/minsk/zamok")],
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


def test_ice_hockey_center_does_not_promise_public_skating() -> None:
    """Олимпик-арена: лёд есть, массового катания нет — ни в title, ни в сниппете."""
    from src.application.place_page import page_title

    view = _place_view(next_slot=None)
    view["card"].update(name="Олимпик-арена", amenities={"hockey_center": True})
    title = page_title(view)
    text = search_description(view)
    assert title == "Олимпик-арена, Минск — каток без массового катания"
    assert text.startswith("Массового катания здесь нет. Ближайшие катки с сеансами")
    assert "Расписание" not in text


def test_no_public_skate_block_points_to_nearest_rinks() -> None:
    from src.application.place_page import _b_schedule_parts

    alt = {
        "arena_name": "ТЦ Замок",
        "path": "/p/minsk/zamok",
        "session_id": 42,
        "day_label": "Сегодня",
        "starts_at_local": "19:00",
        "distance_km": 2.4,
    }
    view = _place_view(next_slot=None, alternatives=[alt], days=[])
    view["card"].update(name="Олимпик-арена", amenities={"hockey_center": True})
    title, body, aside = _b_schedule_parts(view, base_path="", invite=False, links={})
    assert title == "Массовое катание"
    assert "Массового катания здесь нет" in body
    assert 'href="/p/minsk/zamok?s=42"' in body
    assert "Сегодня 19:00 · 2 км" in body
    assert "на сайте катка" not in body
    assert aside == ""

    lonely = _place_view(next_slot=None, alternatives=[], days=[])
    lonely["card"].update(amenities={"hockey_center": True})
    _t, body, _a = _b_schedule_parts(lonely, base_path="", invite=False, links={})
    assert "Покататься можно рядом" not in body


def test_search_description_drops_long_service_list_to_fit_snippet(monkeypatch) -> None:
    from src.application import place_page

    rows = [{"kind": "aid", "title": t} for t in (
        "Прокат детского тренажёра («пингвин»)", "Прокат защитной экипировки и шлема", "Заточка коньков")]
    monkeypatch.setattr(place_page, "_place_visit", lambda v: {"services": {"rows": rows}, "tickets": {"mode": "online"}})
    text = search_description(_place_view())
    assert len(text) <= 160
    assert "пингвин" not in text
    assert "Победителей, 65" in text
