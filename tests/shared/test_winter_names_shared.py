"""Очистка официальных названий seed «Зимой» (строки взяты из seasonal_rinks_seed_2025_26.csv)."""
from __future__ import annotations

import pytest

from src.application.winter_import import plan_rows
from src.application.winter_public import display_name
from src.shared.winter_text import clean_official_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Мобильный каток ГУ «ЦФОР Заводского района г.Минска»", "Мобильный каток Заводского района"),
        ("ГУ «Национальный олимпийский стадион «Динамо»", "Национальный олимпийский стадион «Динамо»"),
        ("Мобильный каток РЦОП по игровым видам спорта «Дворец спорта»", "Мобильный каток «Дворец спорта»"),
        ("Каток ТЦ «Замок» (ООО «Табак-инвест»)", "Каток ТЦ «Замок»"),
        ("ГУ «Хоккейный клуб «Юность-Минск»", "Хоккейный клуб «Юность-Минск»"),
        ("ГУ «Ледовый дворец спорта Минской области»", "Ледовый дворец спорта Минской области"),
        ("УП «Лебяжий парк» НОК РБ (2 коробки)", "Лебяжий парк (2 коробки)"),
        ("Лядовая пляцоўка г. Жодзіна", "Лядовая пляцоўка"),
        ("Каток во дворе", "Каток во дворе"),
    ],
)
def test_official_names_lose_legal_forms_and_town(raw, expected):
    assert clean_official_name(raw) == expected
    assert clean_official_name(expected) == expected  # идемпотентно


@pytest.mark.parametrize("raw", ["СДЮШОР по фигурному катанию", "ГУ «ЦФОР г.Минска»", "Каток", ""])
def test_nothing_meaningful_left_means_generated_name(raw):
    assert clean_official_name(raw) is None


def test_import_cleans_name_or_falls_back_to_address():
    base = {"city": "Минск", "type": "каток", "geocode_precision": "house", "lat": "53.9", "lon": "27.5"}
    rows = [
        {**base, "name": "Мобильный каток ГУ «ЦФОР Заводского района г.Минска»", "address": "ул. Макаёнка, 1"},
        {**base, "name": "СДЮШОР по фигурному катанию", "address": "ул. Тимирязева, 5"},
        {**base, "name": "ГУО «Средняя школа № 144 г.Минска»", "address": "ул. Школьная, 1"},
    ]
    planned = {p.address: p for p in plan_rows(rows)}
    assert planned["ул. Макаёнка, 1"].name == "Мобильный каток Заводского района"
    assert planned["ул. Тимирязева, 5"].name.startswith("Каток, ул. Тимирязева") and planned["ул. Тимирязева, 5"].name_source == "generated"
    assert planned["ул. Школьная, 1"].name_source == "generated"


def test_display_cleans_stored_names_but_not_catalog_arenas():
    assert display_name("Мобильный каток ГУ «ЦФОР Заводского района г.Минска»", True) == "Мобильный каток Заводского района"
    assert display_name("Каток на Немиге у Дворца спорта", False) == "Каток на Немиге у Дворца спорта"
