"""TASK-340: разбор календаря, страницы матча и таблицы Экстралиги hockey.by на сохранённых страницах."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src.ingestion.hockey_sources import MINSK_TZ
from src.ingestion.hockeyby_sources import (
    STATUS_PLAYED,
    STATUS_SCHEDULED,
    calendar_form,
    extract_sessid,
    parse_calendar_response,
    parse_gamecenter,
    parse_standings,
)

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_sessid_from_calendar_page() -> None:
    assert extract_sessid(_page("hockeyby-calendar.html")) == "5c1e9923ed1322282d9f22207690990e"
    assert extract_sessid("<html></html>") is None


def test_calendar_form_matches_the_site_filter() -> None:
    form = dict(calendar_form("abc", page=3))
    assert form["arFilter[0][name]"] == "SEASON" and form["arFilter[0][value]"] == "11"
    assert form["arFilter[2][name]"] == "DIVISION" and form["arFilter[2][value]"] == "628"
    assert (form["view"], form["page"], form["sessid"]) == ("list", "3", "abc")


def test_calendar_page_with_results() -> None:
    page = parse_calendar_response(_page("hockeyby-calendar-p01.json"))
    assert page.season_start_year == 2026 and not page.empty and not page.failed
    assert len(page.matches) == 12
    first = page.matches[0]
    assert first.match_id == "441522"
    assert first.starts_at == datetime(2026, 9, 9, 18, 30, tzinfo=MINSK_TZ)
    assert (first.home, first.away, first.home_club_id, first.away_club_id) == ("Шахтер", "Химик", "12", "15")
    assert first.city == "Солигорск"
    assert (first.status, first.home_score, first.away_score, first.decided_in) == (STATUS_PLAYED, 5, 2, "regulation")


def test_calendar_future_page_has_no_scores_and_late_start() -> None:
    page = parse_calendar_response(_page("hockeyby-calendar-p12.json"))
    assert all(m.status == STATUS_SCHEDULED and m.home_score is None for m in page.matches)
    zhlobin = next(m for m in page.matches if m.match_id == "442032")
    # «Начало матча в 19:25» — другой вид той же строки.
    assert zhlobin.starts_at == datetime(2026, 11, 3, 19, 25, tzinfo=MINSK_TZ)
    assert zhlobin.arena == "Ледовый дворец «Металлург»" and zhlobin.city is None


def test_calendar_page_past_the_season_end_is_empty() -> None:
    page = parse_calendar_response(_page("hockeyby-calendar-p32-empty.json"))
    assert page.empty and page.matches == ()


def test_calendar_error_response_raises() -> None:
    with pytest.raises(ValueError, match="status"):
        parse_calendar_response(json.dumps({"status": "error", "errors": [{"message": "csrf"}]}))


def test_gamecenter_overtime_final() -> None:
    g = parse_gamecenter(_page("hockeyby-gamecenter-441964-ot.html"), match_id="441964")
    assert g.starts_at == datetime(2026, 10, 27, 19, 0, tzinfo=MINSK_TZ)
    assert (g.arena, g.city) == ("Чижовка-Арена", "Минск")
    assert (g.home.club_id, g.home.name, g.away.club_id, g.away.name) == ("10", "Юность", "14", "Неман")
    assert g.official
    assert (g.home_score, g.away_score, g.decided_in) == (3, 2, "ot")
    assert g.periods == ((1, 1), (1, 1), (0, 0), (1, 0))
    assert [(x.minute, x.club_id, x.scorer) for x in g.goals][-1] == ("62:25", "10", "Арсений Ковгореня")
    assert g.goals[2].assists == ("Мурашов Иван", "Соколовский Владислав")
    assert (g.shots, g.penalty_minutes, g.attendance) == ((29, 29), (6, 6), 622)
    assert g.best_players == ("А.Ковгореня", "Мурашов")
    # После игры билета в шапке нет.
    assert g.tickets_url is None


def test_gamecenter_regulation_final_with_video() -> None:
    g = parse_gamecenter(_page("hockeyby-gamecenter-441960-final.html"), match_id="441960")
    assert (g.home_score, g.away_score, g.decided_in, g.official) == (1, 4, "regulation", True)
    assert len(g.goals) == 5 and {x.club_id for x in g.goals} == {"10", "20"}
    assert g.video_url == "https://www.youtube.com/watch?v=A6GfcF0Dorw"


def test_gamecenter_future_match_has_tickets_and_leaders() -> None:
    g = parse_gamecenter(_page("hockeyby-gamecenter-441978-future.html"), match_id="441978")
    assert g.starts_at == datetime(2026, 10, 29, 19, 0, tzinfo=MINSK_TZ)
    assert not g.official and g.home_score is None and g.goals == ()
    assert g.tickets_url == "https://www.ticketpro.by/bilety-na-sportivnye-meropriyatiya/bilety-na-xokkej/"
    top = g.home.forwards[0]
    # Пометка «(Д)» у имени на сайте — служебная, в имя не попадает.
    assert (top.name, top.points, top.goals, top.assists) == ("Дмитрий Хобян", 10, 6, 4)
    assert [p.name for p in g.away.defenders] == ["Евгений Лисовец", "Даниил Криштофик"]
    assert (g.home.goalies[0].name, g.home.goalies[0].save_pct) == ("Ростислав Зиновенко", 91.0)
    assert g.away.goalies[0].save_pct == 92.2


def test_standings() -> None:
    rows = parse_standings(_page("hockeyby-table-628.html"))
    assert len(rows) == 14
    assert (rows[0].place, rows[0].name, rows[0].team_id, rows[0].games, rows[0].points) == (
        1,
        "Шахтер",
        "5674",
        16,
        27,
    )
    by_name = {r.name: r for r in rows}
    assert (by_name["Неман"].place, by_name["Неман"].points) == (7, 18)
    assert (by_name["Юность"].place, by_name["Юность"].points) == (13, 9)


def test_standings_without_table_raises() -> None:
    with pytest.raises(ValueError):
        parse_standings("<html>нет таблицы</html>")
