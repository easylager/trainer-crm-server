"""TASK-296: разбор hcdinamo.by и ленты hockey.by на сохранённых страницах."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from src.ingestion.hockey_sources import (
    MINSK_TZ,
    parse_hcdinamo_calendar,
    parse_hcdinamo_match,
    parse_hockey_by_ticker,
)

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_final_regulation_match() -> None:
    m = parse_hcdinamo_match(_page("hcdinamo-match-final.html"), source_match_id="1218869")
    assert m.starts_at == datetime(2026, 10, 18, 17, 0, tzinfo=MINSK_TZ)
    assert (m.home, m.away) == ("Динамо-Минск", "Ак Барс")
    assert (m.home_score, m.away_score) == (1, 4)
    assert m.parts == ((1, 2), (0, 1), (0, 1))
    assert m.decided_in == "regulation"
    assert m.looks_final


def test_overtime_match_has_four_parts() -> None:
    m = parse_hcdinamo_match(_page("hcdinamo-match-ot.html"), source_match_id="1218838")
    assert (m.home, m.away, m.home_score, m.away_score) == ("Динамо Москва", "Динамо-Минск", 4, 3)
    assert m.decided_in == "ot"
    assert m.looks_final


def test_shootout_counts_one_goal_for_winner() -> None:
    m = parse_hcdinamo_match(_page("hcdinamo-match-so.html"), source_match_id="1218851")
    assert (m.home_score, m.away_score) == (1, 2)
    assert len(m.parts) == 5
    assert m.decided_in == "so"
    assert m.looks_final


def test_upcoming_match_has_no_score() -> None:
    m = parse_hcdinamo_match(_page("hcdinamo-match-upcoming.html"), source_match_id="1218873")
    assert (m.home, m.away) == ("ХК Сочи", "Динамо-Минск")
    assert m.starts_at == datetime(2026, 10, 22, 19, 30, tzinfo=MINSK_TZ)
    assert m.home_score is None and m.away_score is None
    assert not m.looks_final


def test_unknown_markup_raises() -> None:
    with pytest.raises(ValueError):
        parse_hcdinamo_match("<html><body>Матчи</body></html>", source_match_id="1")


def test_calendar_window_ids_in_order_without_duplicates() -> None:
    ids = parse_hcdinamo_calendar(_page("hcdinamo-calendar.html"))
    assert ids[:3] == ["1218846", "1218849", "1218851"]
    assert "1218873" in ids and len(ids) == len(set(ids)) == 12


def test_ticker_marks_completed_khl_and_overtime() -> None:
    items = parse_hockey_by_ticker(_page("hockey-by-ticker.html"))
    khl = [i for i in items if i.league == "КХЛ" and "Динамо Мн" in i.teams]
    assert len(khl) == 1
    assert khl[0].completed
    assert khl[0].local_date == date(2026, 10, 18)
    assert khl[0].teams == ("Динамо Мн", "Ак Барс")
    assert khl[0].points == (1, 4)
    assert khl[0].decided_in == "regulation"
    ot = [i for i in items if i.extra == "ОТ"]
    assert ot and ot[0].decided_in == "ot"
    upcoming = [i for i in items if not i.completed]
    assert upcoming and upcoming[0].points == (None, None)
