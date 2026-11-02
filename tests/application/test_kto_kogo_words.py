"""TASK-334 (W1): в текстах игры нет слов из азартной лексики — игра, а не ставки."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "src/application/hockey_slices.py",
    "src/application/hockey_races.py",
    "src/application/hockey_leagues.py",
    "src/application/hockey_game.py",
    "src/api/routes/webapp_client_hockey.py",
    "src/api/routes/webapp_client_hockey_leagues.py",
    "src/application/hockey_notices.py",
    "src/application/hockey_hub.py",
    "src/application/hockey_event.py",
    "src/application/hockey_screens.py",
    "src/application/hockey_cards.py",
    "src/application/hockey_matches.py",
    "src/application/hockey_review.py",
    "src/application/hockey_teams.py",
    "src/application/hockey_share.py",
    "src/application/hockey_match_share.py",
    "src/api/routes/webapp_client_hockey_event.py",
    "src/api/routes/webapp_client_hockey_screens.py",
    "src/api/routes/webapp_client_hockey_share.py",
    "src/bot/handlers/hockey_game_handlers.py",
)
# «срок» владелец не хочет нигде в игре. Только то, что видит игрок: строки в кавычках (detail, сообщения), без комментариев и docstring-пояснений.
_BANNED = re.compile(r"ставк|коэффициент|прогноз|пари\b|выигрыш|букмекер|банк\b|ставь|поставить|срок", re.I)
_STRING = re.compile(r'(?<![\w"])f?"([^"\n]{3,})"')


@pytest.mark.parametrize("path", FILES)
def test_player_facing_strings_have_no_gambling_words(path: str) -> None:
    source = (ROOT / path).read_text(encoding="utf-8")
    hits = [m.group(1) for m in _STRING.finditer(source) if _BANNED.search(m.group(1))]
    assert not hits, hits
