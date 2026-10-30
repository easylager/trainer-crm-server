from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application.dinamo_stats import sync_dinamo_stats
from src.application.extraliga_preview import match_preview
from src.application.hockey_matches import DECIDED_REGULATION
from src.ingestion.hockey_sources import HCDINAMO_STANDINGS_URL, HCDINAMO_STATS_URL

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)


def _fetch():
    pages = {
        HCDINAMO_STANDINGS_URL: (FIXTURES / "hcdinamo-standings.html").read_text(encoding="utf-8"),
        HCDINAMO_STATS_URL: (FIXTURES / "hcdinamo-statistics.html").read_text(encoding="utf-8"),
    }

    async def fetch(url: str) -> str:
        return pages[url]

    return fetch


async def _add(db, sid, home, away, starts, final=None) -> int:
    hs, as_ = final or (None, None)
    return (
        await db.execute(
            text("""
            INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status, league,
                                        home_score, away_score, decided_in, result_source)
            VALUES ('hcdinamo', :sid, :home, :away, :starts, :status, 'khl', :hs, :as_, :dec, :rsrc)
            RETURNING id
            """),
            {
                "sid": sid,
                "home": home,
                "away": away,
                "starts": starts,
                "status": "final" if final else "scheduled",
                "hs": hs,
                "as_": as_,
                "dec": DECIDED_REGULATION if final else None,
                "rsrc": "auto" if final else None,
            },
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_dinamo_preview_has_table_form_and_leaders(db_session):
    await _add(db_session, "1", "Трактор", "Динамо-Минск", NOW - timedelta(days=5), final=(2, 3))
    await _add(db_session, "2", "Динамо-Минск", "СКА", NOW - timedelta(days=3), final=(1, 4))
    upcoming = await _add(db_session, "3", "Динамо-Минск", "Трактор", NOW + timedelta(hours=9))
    counts = await sync_dinamo_stats(db_session, _fetch(), now=NOW)
    assert counts == {"standings": 22, "leaders_matches": 1}

    p = await match_preview(db_session, upcoming)
    assert p is not None
    home, away = p["home"], p["away"]
    assert (home["place"], away["place"]) == (8, 11)
    assert home["form"] == ["В", "П"] and away["form"] == []  # у соперника — только матчи с Динамо, это не форма
    assert [f["name"] for f in home["leaders"]["forwards"]] == ["Кристофер Тирни", "Тай Смит"]
    assert home["leaders"]["goalie"]["name"] == "Зак Фукале" and away["leaders"]["forwards"] == []
    assert p["last_meeting"]["home_score"] == 2


@pytest.mark.asyncio
async def test_sync_skips_finished_matches(db_session):
    played = await _add(db_session, "1", "Динамо-Минск", "СКА", NOW - timedelta(days=1), final=(5, 2))
    await sync_dinamo_stats(db_session, _fetch(), now=NOW)
    details = (
        await db_session.execute(text("SELECT details FROM hockey_matches WHERE id = :id"), {"id": played})
    ).scalar()
    assert details is None
