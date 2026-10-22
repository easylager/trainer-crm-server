"""Карточка катка v2: настройки админки → модель блоков."""

from __future__ import annotations

import pytest

from src.application.arena_visit_info import (
    PLACE_BLOCKS,
    VisitInfoError,
    normalize_visit_info,
    visit_view,
)

OSTROVETS = {
    "tickets": {"mode": "box_office", "open": "12:30", "close": "21:00", "card": True, "cash": True},
    "child_age_max": 14,
    "facts": {"locker_rooms": {"state": "yes", "note": "переобуться"}, "warmth": {"state": "cool"}},
    "services": [
        {"kind": "sharpening", "price": "10 BYN"},
        {"kind": "aid", "price": "1 BYN"},
        {"kind": "helmet", "price": "1 BYN"},
    ],
    "rental": {"sizes": "26–47", "deposit": "документ, кроме паспорта"},
    "school": {"age_from": 4, "rows": [{"label": "Занятие, 15 минут", "child": "10 BYN", "adult": "15 BYN"}]},
    "passes": {"columns": ["Детский", "Взрослый"], "rows": [{"label": "4", "values": ["15 BYN", "22 BYN"]}]},
    "rink_rental": {"rows": [{"label": "Только лёд", "minutes": 60, "price": "240 BYN"},
                             {"label": "Лёд и раздевалка", "minutes": 60, "price": "265 BYN"}]},
}


def test_normalize_keeps_known_and_drops_empty() -> None:
    raw = dict(OSTROVETS, facts={"cafe": {"state": ""}, "locker_rooms": {"state": "yes"}}, custom_facts=[{"title": ""}])
    out = normalize_visit_info(raw)
    assert out["facts"] == {"locker_rooms": {"state": "yes", "note": ""}}
    assert "custom_facts" not in out
    assert out["tickets"]["open"] == "12:30"


@pytest.mark.parametrize(
    "raw",
    [
        {"tickets": {"mode": "maybe"}},
        {"tickets": {"open": "25:00"}},
        {"child_age_max": 40},
        {"services": [{"kind": "spaceship"}]},
    ],
)
def test_normalize_rejects_what_the_card_cannot_show(raw) -> None:
    with pytest.raises(VisitInfoError):
        normalize_visit_info(raw)


def test_view_box_office_small_rink() -> None:
    view = visit_view({"visit_info": normalize_visit_info(OSTROVETS)}, has_trainers=False)
    assert view["blocks"] == list(PLACE_BLOCKS)
    assert view["tickets"]["mode"] == "box_office"
    assert view["tickets"]["detail"] == "касса 12:30–21:00 · карта, наличные"
    titles = [f["title"] for f in view["facts"]]
    assert titles[:3] == ["Раздевалка есть", "Внутри прохладно", "Карта и наличные"]
    assert "Детский билет до 14 лет" in titles and "Коньки 26–47" in titles and "Учат с 4 лет" in titles
    kinds = [r["kind"] for r in view["services"]["rows"]]
    assert kinds == ["aid", "helmet", "sharpening"]  # пингвин первым
    assert view["services"]["notes"] == ["Коньки выдают под залог: документ, кроме паспорта."]
    more = {m["key"]: m["note"] for m in view["more"]}
    assert more == {"school": "с 4 лет · занятие, 15 минут от 10 BYN", "passes": "от 15 BYN за 4 катания", "rink": "от 240 BYN за час"}


def test_school_moves_into_trainers_when_trainers_exist() -> None:
    view = visit_view({"visit_info": normalize_visit_info(OSTROVETS)}, has_trainers=True)
    assert view["school"]["age_from"] == 4
    assert "school" not in {m["key"] for m in view["more"]}


def test_legacy_fields_fill_the_blocks_without_migration() -> None:
    card = {
        "tickets_url": "",
        "amenities": {"skate_rental": True, "skate_sharpening": True, "locker_rooms": True, "cafe": True},
        "opening_hours": {
            "ticket_note": "Билеты только в кассе дворца",
            "kassa": {"open": "12:30", "close": "21:00"},
            "rental_catalog": [{"label": "Прокат коньков, взрослый", "price": "6 BYN"}],
            "rental_note": "сеанс 45 минут",
        },
    }
    view = visit_view(card)
    assert view["tickets"]["mode"] == "box_office"
    assert view["tickets"]["detail"] == "касса 12:30–21:00"
    assert [f["title"] for f in view["facts"]] == ["Раздевалка есть", "Кафе"]
    rows = view["services"]["rows"]
    assert [(r["title"], r["price"]) for r in rows] == [
        ("Прокат коньков, взрослый", "6 BYN"),
        ("Заточка", ""),
    ]
    assert view["services"]["notes"] == ["Сеанс 45 минут."]


def test_online_without_link_falls_back_to_box_office() -> None:
    view = visit_view({"visit_info": {"tickets": {"mode": "same_day"}}})
    assert view["tickets"]["mode"] == "box_office"
    view = visit_view({"tickets_url": "https://x.by", "visit_info": {"tickets": {"mode": "same_day"}}})
    assert view["tickets"]["mode"] == "same_day"
