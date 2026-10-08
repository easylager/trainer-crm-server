"""TASK-222: строки «Ссылка»/«Другое» и подпись og.png — сегодняшние сеансы первыми."""

from __future__ import annotations

from datetime import date

from src.application.selection_page import selection_share_places


def _view(items, slots):
    return {"venue": None, "when": None, "total": len(items), "items": items, "slots": slots}


def test_share_places_put_today_first_then_time_then_name() -> None:
    today = date(2026, 10, 8)
    items = [
        {"id": 1, "name": "Аа без сеанса"},
        {"id": 2, "name": "Яя вечер"},
        {"id": 3, "name": "Бб утро"},
        {"id": 4, "name": "Вв завтра"},
    ]
    slots = {
        1: [],
        2: [{"local_date": today, "starts_at_local": "19:00"}],
        3: [{"local_date": today, "starts_at_local": "09:30"}],
        4: [{"local_date": date(2026, 10, 9), "starts_at_local": "08:00"}],
    }
    order = [item["name"] for item, _slots in selection_share_places(_view(items, slots), today=today)]
    assert order == ["Бб утро", "Яя вечер", "Аа без сеанса", "Вв завтра"]


def test_share_places_rank_a_place_by_its_earliest_session_of_the_day() -> None:
    today = date(2026, 10, 8)
    items = [{"id": 1, "name": "Поздний"}, {"id": 2, "name": "Ранний"}]
    slots = {
        1: [
            {"local_date": today, "starts_at_local": "21:00"},
            {"local_date": today, "starts_at_local": "22:00"},
        ],
        2: [{"local_date": today, "starts_at_local": "07:15"}],
    }
    rows = selection_share_places(_view(items, slots), today=today)
    assert [item["name"] for item, _slots in rows] == ["Ранний", "Поздний"]
    assert rows[0][1][0]["starts_at_local"] == "07:15", "строка рисует ближайший сеанс места"


def test_share_places_ignore_yesterday_and_read_string_slot_keys() -> None:
    today = date(2026, 10, 8)
    items = [{"id": 5, "name": "Вчера"}, {"id": 6, "name": "Aa сегодня нет"}]
    slots = {"5": [{"local_date": date(2026, 10, 7), "starts_at_local": "10:00"}], 6: []}
    order = [item["name"] for item, _slots in selection_share_places(_view(items, slots), today=today)]
    assert order == ["Aa сегодня нет", "Вчера"]
