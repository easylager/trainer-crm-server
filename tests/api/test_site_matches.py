"""TASK-347: матчи как события сайта — страница, список, лента города, арена, sitemap, .ics, колокольчик."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application import match_bells, site_matches
from src.application.ice_city_day import invalidate_public_city_cache
from src.application.site_matches_page import has_forbidden_words, match_description, match_title
from tests.api.test_public_arenas import _insert_arena, _insert_city

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setenv("SITE_MATCHES_ENABLED", "1")
    monkeypatch.setenv("EXTRALIGA_ENABLED", "1")
    monkeypatch.setenv("EXTRALIGA_CLUBS", "Юность,Шахтер,Неман,Гомель,Металлург Жлобин,Динамо-Молодечно")
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    invalidate_public_city_cache()


async def _world(db):
    """Минск с Чижовка-Ареной и Минск-Ареной; Гродно с Гродно-Ареной."""
    await db.execute(text("DELETE FROM hockey_matches"))
    minsk = await _insert_city(db, name="Минск")
    grodno = await _insert_city(db, name="Гродно")
    chizh = await _insert_arena(db, minsk, name="Чижовка-Арена", address="ул. Ташкентская, 19")
    dinamo = await _insert_arena(db, minsk, name="Минск-Арена", address="пр. Победителей, 111")
    gr = await _insert_arena(db, grodno, name="Гродно-Арена")
    return {"minsk": minsk, "grodno": grodno, "chizh": chizh, "dinamo": dinamo, "gr": gr}


async def _match(
    db, home="Юность", away="Шахтер", *, starts=None, city="Минск", arena="Чижовка-Арена", league="extraliga",
    status="scheduled", scores=None, decided="regulation", tickets="https://hockey.by/tickets/1", details=None, missed=0,
) -> int:
    starts = starts or (NOW + timedelta(days=2)).replace(hour=16, minute=0)
    sid = uuid.uuid4().hex[:10]
    src = "hockeyby" if league == "extraliga" else "hcdinamo"
    h, a = scores if scores else (None, None)
    row = await db.execute(
        text("""
        INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at, status, league, city, arena,
                                    tickets_url, home_score, away_score, decided_in, result_source, details, missed_runs)
        VALUES (:src, :sid, :h, :a, :s, :st, :lg, :city, :arena, :t, :hs, :as_, :d, :rs, CAST(:det AS jsonb), :missed)
        RETURNING id
        """),
        {
            "src": src, "sid": sid, "h": home, "a": away, "s": starts, "st": status, "lg": league, "city": city,
            "arena": arena, "t": tickets, "hs": h, "as_": a, "d": decided if status == "final" else None,
            "rs": "auto" if status == "final" else None, "det": json.dumps(details) if details else None, "missed": missed,
        },
    )
    return int(row.scalar_one())


async def _path(db, mid: int) -> str:
    row = (await db.execute(text("SELECT id, home_team, away_team FROM hockey_matches WHERE id=:i"), {"i": mid})).one()
    return site_matches.match_path(row)


async def _get(path: str, **kw):
    async with _client() as c:
        return await c.get(path, **kw)


# ── Страница матча ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_page_before_has_seo_jsonld_and_actions(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session)
    path = await _path(db_session, mid)
    assert path == f"/m/{mid}-yunost-shakhter"
    r = await _get(path)
    assert r.status_code == 200
    html = r.text
    assert "<title>Юность — Шахтер" in html and "билеты" in html
    assert f'<link rel="canonical" href="https://glide.example{path}"' in html
    assert 'content="index, follow"' in html
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1).replace("\\u003c", "<"))
    assert ld["@type"] == "SportsEvent" and ld["eventStatus"].endswith("EventScheduled")
    assert ld["location"]["name"] == "Чижовка-Арена" and ld["offers"]["url"] == "https://hockey.by/tickets/1"
    assert ld["startDate"].endswith("+03:00")
    # AC3/AC4/AC5: колокольчик → бот, «Кто кого» → Mini App, календарь без Telegram
    assert f"startapp=mbell_{mid}" in html and f"startapp=kkm_{mid}" in html
    assert f"{path}/calendar.ics" in html
    assert "Билеты на матч" in html
    assert not has_forbidden_words(html)


@pytest.mark.asyncio
async def test_match_page_without_ticket_url_has_no_buy_button(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session, tickets=None)
    html = (await _get(await _path(db_session, mid))).text
    assert "Билеты — у клуба и на hockey.by." in html
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    assert '"offers"' not in ld


@pytest.mark.asyncio
async def test_match_page_live_has_no_invented_score(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session, starts=NOW - timedelta(minutes=40))
    html = (await _get(await _path(db_session, mid))).text
    assert "идёт" in html and "счёт — в протоколе" in html
    assert "ПЕРЕД МАТЧЕМ" not in html and "Билеты на матч" not in html
    assert "идёт матч" in re.search(r"<title>(.*?)</title>", html).group(1)


@pytest.mark.asyncio
async def test_match_page_after_with_and_without_protocol(app_use_test_db, db_session):
    await _world(db_session)
    det = {"periods": [[1, 0], [1, 1], [0, 1], [1, 0]], "shots": [34, 27],
           "goals": [{"minute": "08:14", "side": "home", "scorer": "Иванов"}, {"minute": "27:40", "side": "away", "scorer": "Петров"},
                     {"minute": "33:05", "side": "home", "scorer": "Иванов"}, {"minute": "51:12", "side": "away", "scorer": "Петров"},
                     {"minute": "63:48", "side": "home", "scorer": "Иванов"}]}
    full = await _match(db_session, starts=NOW - timedelta(days=1), status="final", scores=(3, 2), decided="ot", details=det)
    bare = await _match(db_session, "Неман", "Гомель", starts=NOW - timedelta(days=1), city="Гродно", arena="Гродно-Арена",
                        status="final", scores=(4, 1))
    html = (await _get(await _path(db_session, full))).text
    assert "3:2 ОТ" in html and "ПО ПЕРИОДАМ" in html and "ГОЛЫ" in html and "34:27" in html and "<b>3:2</b>" in html
    assert "3:2 ОТ" in re.search(r"<title>(.*?)</title>", html).group(1)
    assert "Билеты" not in html
    bare_html = (await _get(await _path(db_session, bare))).text
    assert "4:1" in bare_html and "ПО ПЕРИОДАМ" not in bare_html and "ГОЛЫ" not in bare_html
    assert "m-grid" not in bare_html


@pytest.mark.asyncio
async def test_slug_mismatch_redirects_unknown_404_flag_off_404(app_use_test_db, db_session, monkeypatch):
    await _world(db_session)
    mid = await _match(db_session)
    async with _client() as c:
        r = await c.get(f"/m/{mid}-wrong-slug?x=1", follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == f"/m/{mid}-yunost-shakhter?x=1"
        assert (await c.get("/m/999999-a-b")).status_code == 404
        assert (await c.get("/m/abc")).status_code == 404
        monkeypatch.setenv("SITE_MATCHES_ENABLED", "0")
        assert (await c.get(f"/m/{mid}-yunost-shakhter")).status_code == 404
        assert (await c.get("/hockey")).status_code == 404
        assert (await c.get(f"/m/{mid}-yunost-shakhter/calendar.ics")).status_code == 404


@pytest.mark.asyncio
async def test_club_outside_list_and_unknown_team_and_missing_arena_are_invisible(app_use_test_db, db_session):
    await _world(db_session)
    outside = await _match(db_session, "Брест", "Лида", city="Брест", arena="Брест-Арена")
    unknown = await _match(db_session, "Юность", "Победитель пары")
    no_arena = await _match(db_session, "Юность", "Неман", arena="Неизвестный Дворец")
    for mid in (outside, unknown, no_arena):
        assert (await _get(f"/m/{mid}-x-y")).status_code == 404
        assert (await _get(f"/m/{mid}-x-y/calendar.ics")).status_code == 404


@pytest.mark.asyncio
async def test_missed_and_cancelled_match_keep_page_noindex_but_leave_lists(app_use_test_db, db_session):
    await _world(db_session)
    gone = await _match(db_session, missed=2)
    cancelled = await _match(db_session, "Юность", "Неман", status="cancelled")
    live = await _match(db_session, "Неман", "Гомель", city="Гродно", arena="Гродно-Арена")
    p_gone = await _path(db_session, gone)
    r = await _get(p_gone)
    assert r.status_code == 200 and "noindex" in r.text and "перенесён или отменён" in r.text
    assert "EventPostponed" in r.text and "Билеты" not in r.text and "startapp=" not in r.text
    p_c = await _path(db_session, cancelled)
    assert "EventCancelled" in (await _get(p_c)).text
    assert (await _get(f"{p_gone}/calendar.ics")).status_code == 404
    lst = (await _get("/hockey")).text
    assert (await _path(db_session, live)) in lst and p_gone not in lst and p_c not in lst


@pytest.mark.asyncio
async def test_moved_match_json_ld_and_url_unchanged(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session)
    before = await _path(db_session, mid)
    await db_session.execute(
        text("UPDATE hockey_matches SET previous_starts_at = starts_at, starts_at = starts_at + interval '1 day' WHERE id=:i"), {"i": mid}
    )
    assert await _path(db_session, mid) == before
    html = (await _get(before)).text
    assert "EventRescheduled" in html and "previousStartDate" in html


# ── .ics ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ics_is_utc_crlf_folded_and_attachment(app_use_test_db, db_session):
    await _world(db_session)
    starts = (NOW + timedelta(days=3)).replace(hour=16, minute=0, second=0)
    mid = await _match(db_session, "Металлург Жлобин", "Динамо-Молодечно", starts=starts, city="Минск")
    r = await _get(f"{await _path(db_session, mid)}/calendar.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar") and "charset=utf-8" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"] and f"glide-match-{mid}.ics" in r.headers["content-disposition"]
    body = r.content.decode()
    assert "\r\n" in body and body.startswith("BEGIN:VCALENDAR")
    assert f"DTSTART:{starts.strftime('%Y%m%dT%H%M%SZ')}" in body
    assert "SUMMARY:Металлург Жлобин — Динамо-Молодечно" in body
    assert "TRIGGER:-PT3H" in body and not has_forbidden_words(body)
    for line in body.split("\r\n"):
        assert len(line.encode()) <= 75 or line.startswith(" ") and len(line.encode()) <= 76


def test_ics_fold_never_splits_a_character():
    folded = site_matches._fold("DESCRIPTION:" + "ё" * 80)
    assert all(len(p.encode()) <= 75 for p in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == "DESCRIPTION:" + "ё" * 80


# ── Sitemap ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sitemap_lists_visible_matches_only_and_no_future_lastmod(app_use_test_db, db_session):
    await _world(db_session)
    ok = await _match(db_session)
    hidden_club = await _match(db_session, "Брест", "Лида", city="Брест", arena="Брест-Арена")
    cancelled = await _match(db_session, "Юность", "Неман", status="cancelled")
    old = await _match(db_session, starts=NOW - timedelta(days=40), status="final", scores=(2, 1))
    xml = (await _get("/sitemap.xml")).text
    assert (await _path(db_session, ok)) in xml and "/hockey<" in xml
    for mid in (hidden_club, cancelled, old):
        assert f"/m/{mid}-" not in xml
    stamps = re.findall(r"/m/\d+-[^<]*</loc><lastmod>([^<]+)</lastmod>", xml)
    assert stamps and all(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc) for s in stamps)


@pytest.mark.asyncio
async def test_sitemap_has_no_matches_with_flag_off(app_use_test_db, db_session, monkeypatch):
    await _world(db_session)
    await _match(db_session)
    monkeypatch.setenv("SITE_MATCHES_ENABLED", "0")
    assert "/m/" not in (await _get("/sitemap.xml")).text


# ── Список ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_own_city_first_chip_filter_noindex(app_use_test_db, db_session):
    await _world(db_session)
    day = (NOW + timedelta(days=2)).replace(hour=15, minute=0)
    gr = await _match(db_session, "Неман", "Гомель", starts=day, city="Гродно", arena="Гродно-Арена")
    mn = await _match(db_session, "Юность", "Шахтер", starts=day + timedelta(hours=1))
    html = (await _get("/hockey?city=minsk")).text
    assert html.index(await _path(db_session, mn)) < html.index(await _path(db_session, gr))
    assert "m-row--mine" in html and 'aria-current="true"' in html
    assert "noindex" in html and 'rel="canonical" href="https://glide.example/hockey"' in html
    filtered = (await _get("/hockey?club=neman")).text
    assert (await _path(db_session, gr)) in filtered and (await _path(db_session, mn)) not in filtered and "noindex" in filtered
    plain = (await _get("/hockey")).text
    assert "index, follow" in plain and not has_forbidden_words(plain)


@pytest.mark.asyncio
async def test_list_pause_message_and_empty(app_use_test_db, db_session):
    await _world(db_session)
    assert "Матчей пока нет" in (await _get("/hockey")).text
    await _match(db_session, starts=NOW + timedelta(days=12))
    assert "На этой неделе матчей нет" in (await _get("/hockey")).text


# ── Город и арена ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_city_page_feed_tile_and_bell_only_with_matches(app_use_test_db, db_session):
    w = await _world(db_session)
    r = await _get("/c/minsk")
    assert "Хоккей в Минске" not in r.text and 'data-route="Хоккей"' not in r.text and "matches.css" not in r.text
    mid = await _match(db_session)
    html = (await _get("/c/minsk")).text
    assert "Хоккей в Минске" in html and 'data-route="Хоккей"' in html and "matches.css" in html
    assert (await _path(db_session, mid)) in html and f"startapp=mbell_{mid}" in html
    assert 'aria-label="Напомнить о матче Юность — Шахтер"' in html
    assert not has_forbidden_words(html)
    del w


@pytest.mark.asyncio
async def test_city_without_club_gets_nearby_feed(app_use_test_db, db_session):
    await _world(db_session)
    await _insert_city(db_session, name="Пинск")
    dm = await _match(db_session, "Динамо-Минск", "СКА", league="khl", city=None, arena=None)
    html = (await _get("/c/pinsk")).text
    assert "Хоккей рядом" in html and (await _path(db_session, dm)) in html and "Хоккей в Пинске" not in html


@pytest.mark.asyncio
async def test_arena_page_has_match_row_and_here_block_and_honest_note(app_use_test_db, db_session):
    w = await _world(db_session)
    day = (datetime.now(timezone.utc) + timedelta(days=2))
    local_day = site_matches.local(day.replace(hour=16, minute=0)).date()
    starts = day.replace(hour=16, minute=0)
    mid = await _match(db_session, starts=starts)
    # Катание утром и ничего вечером → «вечернего катания нет»
    await db_session.execute(
        text("""INSERT INTO ice_sessions (arena_id, kind, status, starts_at_utc, ends_at_utc, starts_at_local, ends_at_local,
                local_date, schedule_basis, currency_code)
                VALUES (:a,'public_skate','active',:s,:e,'10:15','11:45',:d,'live','BYN')"""),
        {"a": w["chizh"], "s": starts.replace(hour=7), "e": starts.replace(hour=8, minute=45), "d": local_day},
    )
    r = await _get("/p/minsk/chizhovka-arena")
    html = r.text
    assert "Матчи здесь" in html and "m-ticket" in html and "вечернего катания нет" in html
    assert (await _path(db_session, mid)) in html
    # Сеанс вечером → строка нейтральная, ничего о катании не утверждает
    await db_session.execute(
        text("""INSERT INTO ice_sessions (arena_id, kind, status, starts_at_utc, ends_at_utc, starts_at_local, ends_at_local,
                local_date, schedule_basis, currency_code)
                VALUES (:a,'public_skate','active',:s,:e,'19:30','21:00',:d,'live','BYN')"""),
        {"a": w["chizh"], "s": starts.replace(hour=16, minute=30), "e": starts.replace(hour=18), "d": local_day},
    )
    html2 = (await _get("/p/minsk/chizhovka-arena")).text
    assert "m-ticket" in html2 and "вечернего катания нет" not in html2
    other = (await _get("/p/minsk/minsk-arena")).text
    assert "Матчи здесь" not in other and "m-ticket" not in other


@pytest.mark.asyncio
async def test_arena_without_matches_and_flag_off_unchanged(app_use_test_db, db_session, monkeypatch):
    await _world(db_session)
    await _match(db_session)
    monkeypatch.setenv("SITE_MATCHES_ENABLED", "0")
    html = (await _get("/p/minsk/chizhovka-arena")).text
    assert "Матчи здесь" not in html and "matches.css" not in html


# ── Тексты и границы ─────────────────────────────────────────────────


def test_minsk_day_boundary_and_title_length():
    late = datetime(2026, 11, 13, 20, 59, tzinfo=timezone.utc)   # 23:59 Минск
    after = datetime(2026, 11, 13, 21, 0, tzinfo=timezone.utc)   # 00:00 следующего дня
    assert site_matches.local(late).date().day == 13 and site_matches.local(after).date().day == 14
    row = type("R", (), {"id": 1, "home_team": "Металлург Жлобин", "away_team": "Динамо-Молодечно"})()
    card = site_matches.match_card(
        type("M", (), dict(id=1, league="extraliga", home_team="Металлург Жлобин", away_team="Динамо-Молодечно", arena="Жлобин-Арена-Центральная",
                           city="Жлобин", starts_at=late, status="scheduled", home_score=None, away_score=None, decided_in=None))(),
        now=late - timedelta(days=1),
    )
    data = {"match": card, "arena_name": "Жлобин-Арена-Центральная", "gone": False, "city": "Жлобин", "preview": None, "tickets": None, "goals": [], "row": row}
    assert len(match_title(data)) <= 60
    assert len(match_description(data)) <= 155
    assert site_matches.score_text({"home_score": 3, "away_score": 2, "decided_in": "so"}) == "3:2 Б"


def test_phase_windows():
    row = type("R", (), dict(status="scheduled", home_score=None, away_score=None, starts_at=NOW))()
    f = site_matches.phase_of
    assert f(row, NOW - timedelta(seconds=1)) == "before" and f(row, NOW) == "live"
    assert f(row, NOW + timedelta(hours=3, minutes=29)) == "live" and f(row, NOW + timedelta(hours=3, minutes=31)) == "wait"
    assert f(row, NOW + timedelta(hours=13)) == "review"


@pytest.mark.asyncio
async def test_league_name_is_ours_not_the_sources(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session, tickets="https://hockey.by/x")
    await db_session.execute(text("UPDATE hockey_matches SET details = CAST(:d AS jsonb) WHERE id=:i"),
                             {"d": json.dumps({"league": "Ставка-Экстралига", "goals": []}), "i": mid})
    html = (await _get(await _path(db_session, mid))).text
    assert "Экстралига" in html and not has_forbidden_words(html)


# ── Колокольчик ──────────────────────────────────────────────────────


def test_parse_bell_start():
    assert match_bells.parse_bell_start("mbell_12") == 12
    for bad in ("mbell_", "mbell_0", "mbell_12_x", "watch_12", "kkm_12", None, "mbell_1234567890"):
        assert match_bells.parse_bell_start(bad) is None
    assert match_bells.parse_off_data("mbell_off:7") == 7 and match_bells.parse_off_data("mbell_off:x") is None


@pytest.mark.asyncio
async def test_open_telegram_sends_bell_to_bot_chat_and_game_to_mini_app(app_use_test_db, db_session):
    await _world(db_session)
    async with _client() as c:
        bell = await c.get("/api/public/catalog/open-telegram?startapp=mbell_5&surface=match_page", follow_redirects=False)
        game = await c.get("/api/public/catalog/open-telegram?startapp=kkm_5&surface=match_page", follow_redirects=False)
    assert bell.headers["location"] == "https://t.me/glide_test_bot?start=mbell_5"
    assert "startapp=kkm_5" in game.headers["location"]


@pytest.mark.asyncio
async def test_subscribe_is_idempotent_and_resubscribe_after_off(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session)
    kw = dict(telegram_id=7_100_000_001, match_id=mid, now=NOW)
    first = await match_bells.subscribe(db_session, **kw)
    assert first["state"] == "new" and "Готово" in first["text"] and "за 3 часа" in first["text"]
    second = await match_bells.subscribe(db_session, **kw)
    third = await match_bells.subscribe(db_session, **kw)
    assert second["state"] == third["state"] == "already" and "Уже стоит" in second["text"]
    n = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_match_bells WHERE match_id=:m"), {"m": mid})).scalar_one()
    assert n == 1
    assert await match_bells.unsubscribe(db_session, telegram_id=7_100_000_001, match_id=mid, now=NOW) is True
    assert await match_bells.unsubscribe(db_session, telegram_id=7_100_000_001, match_id=mid, now=NOW) is False
    again = await match_bells.subscribe(db_session, **kw)
    assert again["state"] == "new"


@pytest.mark.asyncio
async def test_subscribe_rejects_unknown_hidden_and_played(app_use_test_db, db_session):
    await _world(db_session)
    outside = await _match(db_session, "Брест", "Лида", city="Брест", arena="Брест-Арена")
    gone = await _match(db_session, missed=2)
    played = await _match(db_session, starts=NOW - timedelta(days=1), status="final", scores=(3, 1))
    kw = dict(telegram_id=7_100_000_002, now=NOW)
    assert await match_bells.subscribe(db_session, match_id=outside, **kw) is None
    assert await match_bells.subscribe(db_session, match_id=987654, **kw) is None
    assert (await match_bells.subscribe(db_session, match_id=gone, **kw))["state"] == "closed"
    r = await match_bells.subscribe(db_session, match_id=played, **kw)
    assert r["state"] == "closed" and "уже сыгран" in r["text"]
    assert (await db_session.execute(text("SELECT COUNT(*) FROM hockey_match_bells"))).scalar_one() == 0


class _Factory:
    """Фабрика сессий поверх одной тестовой сессии: коммиты остаются внутри внешней транзакции."""

    def __init__(self, db):
        self.db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


class _Sink:
    def __init__(self, result="ok"):
        self.sent = []
        self.result = result

    async def __call__(self, chat_id, body, buttons):
        self.sent.append((chat_id, body, buttons))
        return self.result


@pytest.mark.asyncio
async def test_deliver_remind_once_then_moved_then_result(app_use_test_db, db_session, monkeypatch):
    await _world(db_session)
    starts = NOW + timedelta(hours=2, minutes=50)
    mid = await _match(db_session, starts=starts)
    tg = 7_100_000_003
    await match_bells.subscribe(db_session, telegram_id=tg, match_id=mid, now=NOW)
    sink, factory = _Sink(), _Factory(db_session)
    counts = await match_bells.deliver(factory, now=NOW, send=sink)
    assert counts["sent"] == 1 and ("Скоро" in sink.sent[0][1] or "Через 3 часа" in sink.sent[0][1])
    assert any(b.get("callback_data") == f"mbell_off:{mid}" for row in sink.sent[0][2] for b in row)
    await match_bells.deliver(factory, now=NOW + timedelta(minutes=10), send=sink)
    assert len(sink.sent) == 1  # повторный тик не дублирует
    # перенос на сутки позже: одно «перенесён», потом одно новое напоминание
    await db_session.execute(text("UPDATE hockey_matches SET starts_at = :s WHERE id=:i"), {"s": NOW + timedelta(days=1), "i": mid})
    await match_bells.deliver(factory, now=NOW + timedelta(minutes=20), send=sink)
    assert len(sink.sent) == 2 and "перенесён" in sink.sent[1][1]
    await match_bells.deliver(factory, now=NOW + timedelta(minutes=30), send=sink)
    assert len(sink.sent) == 2
    later = NOW + timedelta(days=1) - timedelta(hours=2, minutes=55)
    await match_bells.deliver(factory, now=later, send=sink)
    assert len(sink.sent) == 3 and ("Через 3 часа" in sink.sent[2][1])
    # итог
    await db_session.execute(
        text("UPDATE hockey_matches SET status='final', home_score=3, away_score=2, decided_in='ot', result_source='auto' WHERE id=:i"),
        {"i": mid},
    )
    res_time = NOW + timedelta(days=1, hours=3)
    await match_bells.deliver(factory, now=res_time, send=sink)
    assert len(sink.sent) == 4 and "3:2 ОТ" in sink.sent[3][1] and not has_forbidden_words(sink.sent[3][1])
    await match_bells.deliver(factory, now=res_time + timedelta(minutes=10), send=sink)
    assert len(sink.sent) == 4


@pytest.mark.asyncio
async def test_deliver_unsubscribed_gets_nothing_and_blocked_drops_all(app_use_test_db, db_session):
    await _world(db_session)
    near = NOW + timedelta(hours=2)
    a = await _match(db_session, starts=near)
    b = await _match(db_session, "Неман", "Гомель", starts=near + timedelta(days=1), city="Гродно", arena="Гродно-Арена")
    off, blocked = 7_100_000_004, 7_100_000_005
    await match_bells.subscribe(db_session, telegram_id=off, match_id=a, now=NOW)
    await match_bells.unsubscribe(db_session, telegram_id=off, match_id=a, now=NOW)
    await match_bells.subscribe(db_session, telegram_id=blocked, match_id=a, now=NOW)
    await match_bells.subscribe(db_session, telegram_id=blocked, match_id=b, now=NOW)
    sink = _Sink(result="blocked")
    counts = await match_bells.deliver(_Factory(db_session), now=NOW, send=sink)
    assert [s[0] for s in sink.sent] == [blocked] and counts["blocked"] == 1
    left = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_match_bells WHERE telegram_id=:t AND unsubscribed_at IS NULL"), {"t": blocked})).scalar_one()
    assert left == 0
    sink2 = _Sink()
    await match_bells.deliver(_Factory(db_session), now=NOW + timedelta(minutes=10), send=sink2)
    assert sink2.sent == []


@pytest.mark.asyncio
async def test_deliver_cancel_notice_and_stale_result_skipped(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session, starts=NOW + timedelta(days=1))
    await match_bells.subscribe(db_session, telegram_id=7_100_000_006, match_id=mid, now=NOW)
    await db_session.execute(text("UPDATE hockey_matches SET missed_runs = 2 WHERE id=:i"), {"i": mid})
    sink, f = _Sink(), _Factory(db_session)
    await match_bells.deliver(f, now=NOW, send=sink)
    await match_bells.deliver(f, now=NOW + timedelta(minutes=10), send=sink)
    assert len(sink.sent) == 1 and "отменён" in sink.sent[0][1]
    old = await _match(db_session, "Неман", "Гомель", starts=NOW + timedelta(hours=1), city="Гродно", arena="Гродно-Арена")
    await match_bells.subscribe(db_session, telegram_id=7_100_000_007, match_id=old, now=NOW)
    await db_session.execute(
        text("UPDATE hockey_matches SET status='final', home_score=1, away_score=0, decided_in='regulation', result_source='auto' WHERE id=:i"),
        {"i": old},
    )
    sink2 = _Sink()
    await match_bells.deliver(f, now=NOW + timedelta(hours=30), send=sink2)
    assert all(s[0] != 7_100_000_007 for s in sink2.sent)


# ── Синхронизация календаря: пропавшие матчи ─────────────────────────


@pytest.mark.asyncio
async def test_mark_missed_counts_and_guards_against_broken_parse(app_use_test_db, db_session):
    from src.application import extraliga

    await _world(db_session)
    ids, sids = [], []
    for i in range(12):
        mid = await _match(db_session, starts=NOW + timedelta(days=2 + i))
        ids.append(mid)
    rows = (await db_session.execute(text("SELECT id, source_match_id FROM hockey_matches ORDER BY id"))).all()
    sids = [r.source_match_id for r in rows]
    # пропал один из 12 (8%) — отмечаем
    assert await extraliga.mark_missed(db_session, set(sids[1:]), now=NOW) == 1
    assert await extraliga.mark_missed(db_session, set(sids[1:]), now=NOW) == 1
    assert (await db_session.execute(text("SELECT missed_runs FROM hockey_matches WHERE id=:i"), {"i": rows[0].id})).scalar_one() == 2
    # вернулся в календарь — счётчик сброшен
    await db_session.execute(text("UPDATE hockey_matches SET missed_runs = 0 WHERE id=:i"), {"i": rows[0].id})
    # пропали сразу почти все — это сбой разбора, ничего не трогаем
    assert await extraliga.mark_missed(db_session, set(sids[:2]), now=NOW) == 0
    assert (await db_session.execute(text("SELECT MAX(missed_runs) FROM hockey_matches"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_live_score_shown_only_when_columns_filled(app_use_test_db, db_session):
    await _world(db_session)
    mid = await _match(db_session, starts=NOW - timedelta(minutes=50))
    data = await site_matches.match_page_data(db_session, mid, now=NOW)
    assert data["live"] is None  # колонок живого счёта в этой ветке нет — ссылка на протокол
    await db_session.execute(text("ALTER TABLE hockey_matches ADD COLUMN live_home_score int, ADD COLUMN live_away_score int, ADD COLUMN live_at timestamptz"))
    await db_session.execute(text("UPDATE hockey_matches SET live_home_score=2, live_away_score=1, live_at=:t WHERE id=:i"), {"t": NOW, "i": mid})
    html = (await _get(await _path(db_session, mid))).text
    assert "2 : 1" in html and "обновлено в" in html
