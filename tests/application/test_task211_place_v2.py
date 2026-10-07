"""TASK-211: статус места, цена с прокатом, дни без JS, ОХМ, режимы, служебные пометки."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, text

from src.application.place_page import render_place_page
from src.application.place_v2 import choose_schedule_day, day_tab_label, session_price_view, skate_status
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city
from tests.api.test_public_place_page import _client, _place

MINSK = ZoneInfo("Europe/Minsk")
_NOW = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)  # 13:00 Минск
_TODAY = date(2026, 10, 8)  # четверг


def _slot(
    *,
    start: datetime,
    end: datetime,
    local: date,
    hhmm: str,
    basis: str = "live",
    kind: str = "public_skate",
    adult: int | None = 1000,
    child: int | None = 700,
    rental: int | None = None,
    label: str | None = None,
    sid: int = 1,
) -> dict:
    return {
        "id": sid,
        "kind": kind,
        "starts_at_utc": start.isoformat(),
        "ends_at_utc": end.isoformat(),
        "local_date": local.isoformat(),
        "starts_at_local": hhmm,
        "ends_at_local": end.astimezone(MINSK).strftime("%H:%M"),
        "schedule_basis": basis,
        "price_adult_minor": adult,
        "price_child_minor": child,
        "price_rental_minor": rental,
        "currency_code": "BYN",
        "session_label": label,
    }


def test_status_four_branches_and_projected_is_not_live() -> None:
    live = _slot(
        start=_NOW - timedelta(minutes=20),
        end=_NOW + timedelta(minutes=40),
        local=_TODAY,
        hhmm="12:40",
    )
    kind, text = skate_status([live], now=_NOW, today=_TODAY)
    assert kind == "now"
    assert text == "Сейчас идёт · осталось 40 мин"

    projected = dict(live, schedule_basis="projected")
    kind, text = skate_status([projected], now=_NOW, today=_TODAY)
    assert kind == "none"
    assert "Сейчас идёт" not in text

    later_today = _slot(
        start=_NOW + timedelta(hours=2),
        end=_NOW + timedelta(hours=3),
        local=_TODAY,
        hhmm="15:00",
    )
    kind, text = skate_status([projected, later_today], now=_NOW, today=_TODAY)
    assert kind == "today"
    assert text == "Сегодня есть лёд · ближайший в 15:00"
    assert "Сейчас идёт" not in text

    tomorrow = _slot(
        start=_NOW + timedelta(days=1),
        end=_NOW + timedelta(days=1, hours=1),
        local=_TODAY + timedelta(days=1),
        hhmm="13:00",
    )
    kind, text = skate_status([tomorrow], now=_NOW, today=_TODAY)
    assert kind == "later"
    assert text == "Сегодня сеансов нет. Ближайший — завтра в 13:00"

    friday = _slot(
        start=_NOW + timedelta(days=1),
        end=_NOW + timedelta(days=1, hours=1),
        local=date(2026, 10, 9),
        hhmm="18:00",
    )
    # 9 октября 2026 — пятница, но это завтра от четверга 8-го, так что «завтра».
    assert skate_status([friday], now=_NOW, today=_TODAY)[1].endswith("завтра в 18:00")
    saturday = _slot(
        start=_NOW + timedelta(days=2),
        end=_NOW + timedelta(days=2, hours=1),
        local=date(2026, 10, 10),
        hhmm="11:00",
    )
    assert skate_status([saturday], now=_NOW, today=_TODAY)[1] == (
        "Сегодня сеансов нет. Ближайший — сб в 11:00"
    )
    assert skate_status([], now=_NOW, today=_TODAY) == ("none", "Ближайших сеансов нет")


def test_price_with_rental_is_adult_plus_rental() -> None:
    primary, secondary = session_price_view(
        _slot(
            start=_NOW,
            end=_NOW + timedelta(hours=1),
            local=_TODAY,
            hhmm="13:00",
            adult=1000,
            child=700,
            rental=500,
            label="Малая арена",
        )
    )
    assert primary == "10 BYN · дети 7"
    assert secondary == "Малая арена · с прокатом 15 BYN"
    _primary, without = session_price_view(
        _slot(
            start=_NOW,
            end=_NOW + timedelta(hours=1),
            local=_TODAY,
            hhmm="13:00",
            adult=1000,
            child=None,
            rental=None,
            label="Малая арена",
        )
    )
    assert "прокатом" not in without
    assert without == "Малая арена"


def test_day_tabs_count_matches_the_chosen_day() -> None:
    today = _TODAY
    by_day = {_TODAY.isoformat(): [], (_TODAY + timedelta(days=1)).isoformat(): [{}, {}]}
    assert choose_schedule_day(by_day, today=today, requested=None) == _TODAY + timedelta(days=1)
    assert choose_schedule_day(by_day, today=today, requested=_TODAY) == _TODAY
    assert day_tab_label(_TODAY, today=today, count=0) == "Сегодня · 0"
    assert day_tab_label(_TODAY + timedelta(days=1), today=today, count=2) == "Завтра · 2"


def _render(card: dict, **view) -> str:
    payload = {
        "card": {
            "id": 1,
            "name": "Каток",
            "venue_type": "ice",
            "has_skating": True,
            "city_name": "Минск",
            "timezone": "Europe/Minsk",
            "in_season": True,
            "schedule_mode": "auto",
            "trainer_count": 0,
            "freshness": {},
            **card,
        },
        "days": view.get("days", []),
        "ohm_sessions": view.get("ohm_sessions", []),
        "nearby": view.get("nearby"),
        "focus": None,
        "focus_missing": False,
        "next_slot": None,
        "session_count": 0,
        "schedule_level": "fresh",
        "schedule_note": "",
        "today": _TODAY,
        "now": _NOW,
    }
    return render_place_page(
        payload,
        canonical_url="https://glide.example/p/minsk/katok",
        base_path="/p/minsk/katok",
        og_image_url="/og.png",
        story_image_url="/story.png",
        cta_url=None,
        city_page_url=None,
        share={"share_url": "https://glide.example/p/minsk/katok", "share_text": "x", "share_body": "x"},
        day=view.get("day"),
    )


def test_ohm_is_outside_public_skate_and_hidden_without_sessions() -> None:
    ohm = _slot(
        start=_NOW + timedelta(days=2),
        end=_NOW + timedelta(days=2, hours=1),
        local=date(2026, 10, 10),
        hhmm="08:45",
        kind="hockey_practice",
        adult=1700,
        child=None,
        label="большая арена",
        sid=9,
    )
    ohm["age_note"] = "Только в полной экипировке"
    skate = _slot(
        start=_NOW + timedelta(hours=2),
        end=_NOW + timedelta(hours=3),
        local=_TODAY,
        hhmm="15:00",
        sid=3,
    )
    html = _render({}, days=[{"local_date": _TODAY.isoformat(), "sessions": [skate]}], ohm_sessions=[ohm])
    assert "Хоккей для любителей (ОХМ)" in html
    assert "17 BYN / 60 мин" in html
    assert "Только в полной экипировке" in html
    skate_list = html.split("Хоккей для любителей")[0]
    assert "08:45" not in skate_list
    assert "15:00" in skate_list
    assert "Хоккей для любителей" not in _render({}, days=[{"local_date": _TODAY.isoformat(), "sessions": [skate]}])


def test_invite_link_is_session_query_not_a_new_page() -> None:
    skate = _slot(
        start=_NOW + timedelta(hours=2),
        end=_NOW + timedelta(hours=3),
        local=_TODAY,
        hhmm="15:00",
        sid=3,
    )
    html = _render({}, days=[{"local_date": _TODAY.isoformat(), "sessions": [skate]}])
    assert 'href="/p/minsk/katok?s=3&amp;i=1"' in html or 'href="/p/minsk/katok?s=3&i=1"' in html
    assert 'aria-label="Позвать с собой на 15:00"' in html


def test_phone_and_closed_modes() -> None:
    phone = _render({"schedule_mode": "phone", "phone": "+375 29 111-22-33"})
    assert "Расписание — только по телефону" in phone
    assert "tel:+375291112233" in phone
    assert "Сеанс в … будет?" in phone
    assert "Массовое катание</h2>" not in phone
    missing = _render({"schedule_mode": "phone", "phone": None})
    assert "Телефон уточняем" in missing
    assert "Сообщить об ошибке" in missing
    closed = _render(
        {
            "schedule_mode": "season_closed",
            "schedule_mode_note": "Обычно открывается осенью",
            "phone": "+375 29 000-00-00",
            "latitude": 54.1,
            "longitude": 28.3,
            "city_id": 2,
        },
        nearby={"name": "Минск", "rinks": 2, "today_sessions": 3, "km": 40},
    )
    assert "Сейчас закрыто — межсезонье" in closed
    assert "Обычно открывается осенью" in closed
    assert "Сообщить об открытии" in closed or "Узнайте первым" in closed
    assert "Минск" in closed and "2 катка" in closed and "3 сеанса сегодня" in closed
    assert "около 40 км" in closed
    assert "Когда начнётся массовое катание?" in closed
    assert "Массовое катание</h2>" not in closed


def test_fixture_cards_do_not_leak_dossier_markers() -> None:
    root = Path(__file__).resolve().parents[2] / "data" / "arena-cards"
    files = sorted(root.rglob("*.md"))
    assert files, "нет карточек-фикстур"
    needles = ("unknown", "Conflicts", "склеивать")
    for path in files:
        text = path.read_text(encoding="utf-8")
        fields: dict[str, str] = {}
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2 or cells[0] in {"field", "---"}:
                continue
            if cells[0] in {"district", "phone", "short_description", "opening_hours"}:
                fields[cells[0]] = cells[1]
        amenities: dict[str, bool] = {}
        for part in fields.get("amenities", "").split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            amenities[key.strip()] = value.strip().lower() == "true"
        html = _render(
            {
                "name": path.stem,
                "district": fields.get("district"),
                "phone": fields.get("phone"),
                "short_description": fields.get("short_description"),
                "opening_hours": {"note": fields.get("opening_hours")},
                "amenities": amenities,
                "schedule_mode_note": fields.get("opening_hours"),
            }
        )
        for needle in needles:
            assert needle not in html, f"{path.name}: {needle}"


@pytest.mark.asyncio
async def test_day_query_selects_that_day_without_js(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_bot")
    place = await _place(db_session)
    await _add_future_session(db_session, place["arena_id"], days_ahead=0, starts_at_local="09:00")
    await _add_future_session(db_session, place["arena_id"], days_ahead=1, starts_at_local="21:10")
    await db_session.commit()
    tomorrow = (datetime.now(MINSK).date() + timedelta(days=1)).isoformat()
    async with _client() as client:
        page = await client.get(place["path"], params={"d": tomorrow})
    html = page.text
    assert page.status_code == 200
    assert "21:10" in html
    selected = re.search(r'class="daytab daytab--on"[^>]*>([^<]+)', html)
    assert selected, html
    assert selected.group(1).startswith("Завтра · ")
    count = int(selected.group(1).rsplit("·", 1)[-1].strip())
    assert len(re.findall(r'class="sess(?: sess--projected)?"', html)) == count


@pytest.mark.asyncio
async def test_in_progress_live_session_is_happening_now(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    sid = await _add_future_session(db_session, place["arena_id"], days_ahead=0, starts_at_local="12:00")
    now = datetime.now(timezone.utc)
    local = now.astimezone(MINSK)
    start = (local - timedelta(minutes=15)).replace(second=0, microsecond=0)
    end = start + timedelta(minutes=60)
    await db_session.execute(
        text(
            """
            UPDATE ice_sessions
            SET starts_at_utc = :start, ends_at_utc = :end,
                local_date = :day, starts_at_local = :hhmm, ends_at_local = :end_hhmm,
                schedule_basis = 'live'
            WHERE id = :id
            """
        ),
        {
            "id": sid,
            "start": start.astimezone(timezone.utc),
            "end": end.astimezone(timezone.utc),
            "day": start.date(),
            "hhmm": start.time().replace(microsecond=0),
            "end_hhmm": end.time().replace(microsecond=0),
        },
    )
    await db_session.commit()
    async with _client() as client:
        html = (await client.get(place["path"])).text
    assert "Сейчас идёт · осталось" in html


@pytest.mark.asyncio
async def test_closed_page_points_at_a_real_city_with_sessions(app_use_test_db, db_session, monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_bot")
    near = await _insert_city(db_session, name=f"Рядомск {__import__('uuid').uuid4().hex[:4]}")
    rink = await _insert_arena(db_session, near, name="Живой лёд", latitude=53.9, longitude=27.56)
    await _add_future_session(db_session, rink, days_ahead=1, starts_at_local="18:00")
    closed_city = await _insert_city(db_session, name=f"Тихий {__import__('uuid').uuid4().hex[:4]}")
    closed = await _insert_arena(
        db_session, closed_city, name="Закрытый каток", latitude=54.6, longitude=28.5, phone="+375 17 000-00-01"
    )
    await db_session.execute(
        text("UPDATE arena_profiles SET schedule_mode = 'season_closed' WHERE arena_id = :id"),
        {"id": closed},
    )
    await db_session.commit()
    from src.application.ice_city_day import city_slug

    slug = (
        await db_session.execute(text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": closed})
    ).scalar_one()
    city_name = (
        await db_session.execute(text("SELECT name FROM cities WHERE id = :id"), {"id": closed_city})
    ).scalar_one()
    bind = db_session.sync_session.get_bind()
    seen: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join((statement or "").split())
        if sql.lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            seen.append(sql)

    event.listen(bind, "before_cursor_execute", _before)
    try:
        async with _client() as client:
            html = (await client.get(f"/p/{city_slug(city_name)}/{slug}")).text
    finally:
        event.remove(bind, "before_cursor_execute", _before)
    assert "Сейчас закрыто — межсезонье" in html
    assert f"start=follow_{closed}" in html
    assert "startapp=follow_" not in html
    assert "Рядомск" in html
    assert "/c/" in html
    # Обычный /p/ — 7 холодных. Рядом добавляет один запрос и не сканирует каталог по арене.
    assert len(seen) <= 8, seen
    assert any("AVG(a.latitude)" in sql for sql in seen)
    for sql in seen:
        assert "GROUP BY s.arena_id" not in sql
        assert "GROUP BY ta.arena_id" not in sql
