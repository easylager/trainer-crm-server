from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_matches import DECIDED_REGULATION
from src.application.matches_catalog import Filters, catalog
from src.shared.config import Settings

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
CFG = Settings(extraliga_enabled=True, extraliga_clubs="Юность,Неман,Гомель", hockey_matches_enabled=True)  # type: ignore[call-arg]


async def _add(db, sid, home, away, starts, *, league="extraliga", city=None, arena=None, final=None):
    source = "hcdinamo" if league == "khl" else "hockeyby"
    status = "final" if final else "scheduled"
    hs, as_ = final or (None, None)
    await db.execute(
        text("""
        INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status, league,
                                    city, arena, home_score, away_score, decided_in, result_source)
        VALUES (:src, :sid, :home, :away, :starts, :status, :league, :city, :arena, :hs, :as_, :dec, :rsrc)
        """),
        {
            "src": source,
            "sid": sid,
            "home": home,
            "away": away,
            "starts": starts,
            "status": status,
            "league": league,
            "city": city,
            "arena": arena,
            "hs": hs,
            "as_": as_,
            "dec": DECIDED_REGULATION if final else None,
            "rsrc": "auto" if final else None,
        },
    )


async def _seed(db):
    # Города у части матчей hockey.by нет — берём город хозяина.
    await _add(db, "1", "Юность", "Неман", NOW + timedelta(days=6), arena="Чижовка-Арена")
    await _add(db, "2", "Динамо-Минск", "Трактор", NOW + timedelta(days=1), league="khl")
    await _add(db, "3", "СКА", "Динамо-Минск", NOW + timedelta(days=3), league="khl")
    await _add(db, "4", "Гомель", "Юность", NOW + timedelta(days=2), city="Гомель", arena="Ледовый дворец г. Гомель")
    await _add(db, "5", "Неман", "Гомель", NOW - timedelta(days=2), city="Гродно", arena="Ледовый дворец", final=(3, 1))
    await _add(db, "6", "Шахтер", "Лида", NOW + timedelta(days=1), city="Солигорск")  # клуб не включён


@pytest.mark.asyncio
async def test_catalog_mixes_leagues_by_time(db_session):
    await _seed(db_session)
    out = await catalog(db_session, now=NOW, filters=Filters(), settings=CFG)
    assert [(m["home"]["name"], m["league"]) for m in out["matches"]] == [
        ("Динамо-Минск", "khl"),
        ("Гомель", "extraliga"),
        ("СКА", "khl"),
        ("Юность", "extraliga"),
    ]
    home, away = out["matches"][0], out["matches"][2]
    assert home["href"].startswith("client-match?id=") and home["city"] == "Минск" and home["arena"] == "Минск-Арена"
    assert away["href"] is None and away["external_url"] == "https://hcdinamo.by/matches/3/"
    assert [t["name"] for t in out["facets"]["teams"]][:2] == ["Динамо-Минск", "Гомель"]
    assert {lg["id"] for lg in out["facets"]["leagues"]} == {"khl", "extraliga"}


@pytest.mark.asyncio
async def test_catalog_filters_team_city_arena(db_session):
    await _seed(db_session)
    yunost = await catalog(db_session, now=NOW, filters=Filters(team="yunost"), settings=CFG)
    assert [m["away"]["name"] for m in yunost["matches"]] == ["Юность", "Неман"]
    assert yunost["filters"]["team_card"]["name"] == "Юность"
    minsk = await catalog(db_session, now=NOW, filters=Filters(city="минск"), settings=CFG)
    assert [m["home"]["name"] for m in minsk["matches"]] == ["Динамо-Минск", "Юность"]
    assert {a["name"] for a in minsk["facets"]["arenas"]} == {"Минск-Арена", "Чижовка-Арена"}
    arena = await catalog(db_session, now=NOW, filters=Filters(city="Минск", arena="Чижовка-Арена"), settings=CFG)
    assert [m["home"]["name"] for m in arena["matches"]] == ["Юность"]
    khl = await catalog(db_session, now=NOW, filters=Filters(league="khl"), settings=CFG)
    assert {m["league"] for m in khl["matches"]} == {"khl"} and khl["filters"]["league_label"] == "КХЛ"


@pytest.mark.asyncio
async def test_catalog_results_and_flags(db_session):
    await _seed(db_session)
    res = await catalog(db_session, now=NOW, filters=Filters(when="results"), settings=CFG)
    assert [m["result"]["home_score"] for m in res["matches"]] == [3]
    off = Settings(extraliga_enabled=False, hockey_matches_enabled=False)  # type: ignore[call-arg]
    assert (await catalog(db_session, now=NOW, filters=Filters(), settings=off))["matches"] == []
