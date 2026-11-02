"""Ссылка «Страница матча» в игре — только там, где client-match её откроет."""

import src.application.hockey_event as hockey_event
from src.api.routes.webapp_client_hockey import has_match_page
from src.application.hockey_matches import DINAMO


def test_home_dinamo_match_has_page():
    assert has_match_page({"league": "khl", "home_team": DINAMO}) is True


def test_away_dinamo_match_has_no_page():
    assert has_match_page({"league": "khl", "home_team": "СКА"}) is False


def test_extraliga_match_follows_flag(monkeypatch):
    monkeypatch.setattr(hockey_event, "_extraliga_on", lambda: True)
    assert has_match_page({"league": "extraliga", "home_team": "Юность"}) is True
    monkeypatch.setattr(hockey_event, "_extraliga_on", lambda: False)
    assert has_match_page({"league": "extraliga", "home_team": "Юность"}) is False
