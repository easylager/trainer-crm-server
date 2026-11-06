"""Панель «Кто кого» на странице матча: после старта доли «за кого» — людьми, без процентов и полоски."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from src.application.site_matches import PHASE_BEFORE, PHASE_LIVE
from src.application.site_matches_page import _game_card

ROW = SimpleNamespace(home_team="Динамо-Минск", away_team="Шахтер")
MATCH = {"id": 7, "title": "Динамо-Минск — Шахтёр"}
BASE = "https://glide.example"


def _card(game: dict) -> str:
    return _game_card({"game": game, "match": MATCH, "row": ROW}, base_url=BASE, city_id=None)


def test_live_panel_counts_people_without_percent_or_split() -> None:
    html = _card({"kind": "game", "phase": PHASE_LIVE, "match_id": 7, "next": None, "total": 64, "home_n": 41, "away_n": 23, "right": 0})
    assert "За Динамо-Минск — 41 игрок, за Шахтёр — 23." in html
    assert "%" not in html
    assert "m-split" not in html


def test_live_panel_hides_counts_below_the_threshold_and_names_the_next_match() -> None:
    nxt = {"id": 8, "away": "Шахтер", "starts_at": datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc)}
    html = _card({"kind": "game", "phase": PHASE_LIVE, "match_id": 7, "next": nxt, "total": 3, "home_n": None, "away_n": None, "right": 0})
    assert "Следующий: Динамо-Минск — Шахтёр, 12 ноября." in html
    assert "За Динамо-Минск" not in html
    assert "Сделать ход на следующий матч" in html


def test_soon_panel_offers_a_reminder_not_an_invite() -> None:
    html = _card({"kind": "soon", "match_id": 7})
    assert "Игра в Экстралиге скоро появится на сайте" in html
    assert "Напомнить в Telegram" in html
    assert "позвать" not in html.lower()


def test_before_panel_unchanged_call_to_action() -> None:
    html = _card({"kind": "game", "phase": PHASE_BEFORE, "match_id": 7, "next": None, "total": 0, "home_n": None, "away_n": None, "right": 0})
    assert "Угадай, кто победит" in html
