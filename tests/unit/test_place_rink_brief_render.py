"""TASK-424: строка-ответ и штамп на странице катка Минска; регионы — байт в байт как раньше."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest

from src.application import place_page
from src.application.place_page import render_place_page, search_description

TODAY = date(2026, 11, 16)  # понедельник
NOW = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)  # 10:00 по Минску
REGIONS = ("Мозырь", "Берёза", "Молодечно")


def _slot(sid: int, offset: int, start: str, minutes: int, price: int, kind: str = "public_skate") -> dict:
    h, m = (int(x) for x in start.split(":"))
    end = h * 60 + m + minutes
    day = TODAY + timedelta(days=offset)
    starts_utc = datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc) - timedelta(hours=3)
    return {
        "id": sid,
        "arena_id": 3,
        "kind": kind,
        "local_date": day.isoformat(),
        "starts_at_local": f"{h:02d}:{m:02d}",
        "ends_at_local": f"{end // 60:02d}:{end % 60:02d}",
        "starts_at_utc": starts_utc.isoformat(),
        "price_adult_minor": price,
        "price_child_minor": 800,
        "price_rental_minor": 900,
        "currency_code": "BYN",
        "status": "active",
    }


def _view(city: str, *, ohm: bool = False, mode: str = "auto", fresh: bool = True) -> dict:
    days, sid = [], 1
    for offset in range(7):
        weekend = (TODAY + timedelta(days=offset)).weekday() >= 5
        sessions = []
        for hour in range(10, 23):
            sessions.append(_slot(sid, offset, f"{hour}:15", 45, 1100 if weekend else 1000))
            sid += 1
        days.append({"local_date": (TODAY + timedelta(days=offset)).isoformat(), "sessions": sessions})
    ohm_days = [
        {
            "local_date": (TODAY + timedelta(days=o)).isoformat(),
            "sessions": [_slot(900 + o, o, "13:00", 60, 1400, "hockey_practice")],
        }
        for o in (0, 1, 3, 6)
    ]
    observed = "2026-11-15T23:04:27+00:00" if fresh else "2026-11-10T10:00:00+00:00"
    card = {
        "id": 3,
        "city_id": 2,
        "name": "ТЦ Замок",
        "venue_type": "ice",
        "city_name": city,
        "slug": "zamok",
        "address": "пр-т Победителей, 65",
        "district": "Центральный район",
        "phone": "+375447838518",
        "website_url": "https://tczamok.by/entertainments/ice-rink",
        "tickets_url": "https://tczamok.by/tickets",
        "schedule_mode": mode,
        "in_season": True,
        "currency_code": "BYN",
        "amenities": {"skate_rental": True},
        "visit_info": {"tickets": {"mode": "online"}},
        "freshness": {
            "schedule_observed_at": observed,
            "schedule_auto": True,
            "schedule_stale": False,
            "source_url": "https://tczamok.by/entertainments/ice-rink",
        },
    }
    if mode != "auto":
        days, ohm_days = [], []
    return {
        "card": card,
        "matches": [],
        "matches_by_day": {},
        "trainers": [],
        "days": days,
        "ohm_days": ohm_days if ohm else [],
        "figure_days": [],
        "family_days": [],
        "focus": None,
        "focus_missing": False,
        "next_slot": days[0]["sessions"][0] if days else None,
        "session_count": sum(len(d["sessions"]) for d in days),
        "schedule_note": "",
        "alternatives": [],
        "nearby": [],
        "today": TODAY,
        "now": NOW,
    }


def _render(view: dict) -> str:
    html = render_place_page(
        view,
        canonical_url="https://glideclub.by/p/x/zamok",
        base_path="/p/x/zamok",
        og_image_url="https://glideclub.by/og.png",
        story_image_url="https://glideclub.by/s.png",
        cta_url=None,
        city_page_url="https://glideclub.by/c/x",
        share={"share_url": "https://glideclub.by/p/x/zamok", "text": "", "title": ""},
    )
    return re.sub(r"© Glide \d+", "", html)


def _without_nosnippet(html: str) -> str:
    """Текст, который поисковик может взять в сниппет: всё, кроме поддеревьев с data-nosnippet."""
    from html.parser import HTMLParser

    void = {"br", "img", "input", "meta", "link", "hr", "source", "path"}

    class _Open(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.depth = 0  # >0 — внутри data-nosnippet
            self.out: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag in void:
                return
            if self.depth:
                self.depth += 1
            elif any(k == "data-nosnippet" for k, _v in attrs):
                self.depth = 1
            if not self.depth:
                self.out.append(f"<{tag} {' '.join(f'{k}={v}' for k, v in attrs)}>")

        def handle_endtag(self, tag):
            if tag in void:
                return
            if self.depth:
                self.depth -= 1

        def handle_data(self, data):
            if not self.depth:
                self.out.append(data)

    parser = _Open()
    parser.feed(html)
    return "".join(parser.out)


def _schedule(html: str) -> str:
    start = html.index('id="schedule"')
    return html[html.rindex("<section", 0, start) : html.index("</section>", start)]


@pytest.mark.parametrize("ohm", [False, True])
def test_minsk_answer_line_is_open_to_snippet_sessions_and_stamp_are_not(ohm: bool) -> None:
    html = _render(_view("Минск", ohm=ohm))
    sched = _schedule(html)
    line = "Каждый день 13 сеансов по 45 минут — каждый час с 10:15 до 22:15."
    glued = line.replace("по 45", "по&nbsp;45").replace("с 10", "с&nbsp;10").replace("до 22", "до&nbsp;22")
    assert f'<p class="b-brief">{glued}</p>' in sched
    assert 'id="schedule" data-nosnippet' not in html
    open_text = _without_nosnippet(sched)
    assert line in open_text.replace("\xa0", " ")
    assert "Проверено" not in open_text
    assert "b-ticket" not in open_text and "сегодня" not in open_text and "завтра" not in open_text
    assert '<div class="b-proof" data-nosnippet>' in sched
    assert 'Проверено 16.11 на&nbsp;<a href="https://tczamok.by/entertainments/ice-rink"' in sched
    assert 'data-glide-track="proof_source_click"' in sched
    assert "<div data-glide-session-list-root data-nosnippet>" in sched
    assert "В сб и вс взрослый — 11 BYN." in sched
    # Свежий штамп — и оговорка «Расписание может меняться» в подвале уходит.
    assert "Расписание может меняться" not in html


def test_minsk_ohm_tab_leads_with_answer_and_hides_its_strip() -> None:
    sched = _schedule(_render(_view("Минск", ohm=True)))
    pane = sched[sched.index("b-pane--ohm") :]
    assert '<p class="b-brief">ОХМ: пн, вт, чт и вс — один сеанс в день по&nbsp;60 минут, в&nbsp;13:00.</p>' in pane
    assert '<nav class="b-sched" aria-label="День" data-nosnippet>' in pane


def test_answer_line_has_no_dates_or_relative_days() -> None:
    sched = _schedule(_render(_view("Минск", ohm=True)))
    for line in re.findall(r'<p class="b-brief">(.*?)</p>', sched):
        assert not re.search(r"сегодня|завтра|\d{1,2}\.\d{2}|\b(ноя|дек)", line, re.I), line


def test_stale_data_gets_no_stamp_and_keeps_footer_disclaimer() -> None:
    html = _render(_view("Минск", fresh=False))
    assert "b-proof" not in html
    assert "Проверено" not in html
    assert "Расписание может меняться — уточняйте у катка." in html
    assert '<p class="b-brief">' in html  # строка-ответ от свежести не зависит


def test_minsk_closed_season_without_date_says_so_and_offers_watch() -> None:
    html = _render(_view("Минск", mode="season_closed"))
    sched = _schedule(html)
    assert "Дату открытия мы пока не знаем." in sched
    assert "Расписание может меняться" in html  # штампа нет — оговорка остаётся


@pytest.mark.parametrize("city", REGIONS)
@pytest.mark.parametrize("kw", [{"ohm": False}, {"ohm": True}, {"mode": "season_closed"}])
def test_region_pages_are_byte_identical_to_the_gate_off_path(city: str, kw: dict, monkeypatch) -> None:
    html = _render(_view(city, **kw))
    assert "b-brief" not in html and "b-proof" not in html
    assert "Расписание может меняться — уточняйте у катка." in html
    if "mode" not in kw and not kw.get("ohm"):
        assert 'id="schedule" data-nosnippet' in html
    monkeypatch.setattr(place_page, "_brief_on", lambda view: False)
    assert _render(_view(city, **kw)) == html


def test_minsk_description_leads_with_answer_line_and_fits() -> None:
    text = search_description(_view("Минск"))
    assert text.startswith("Каждый день 13 сеансов по 45 минут — каждый час с 10:15 до 22:15. ")
    assert "Вход от 10 BYN" in text
    assert len(text) <= 160
    assert not re.search(r"сегодня|завтра|\d{1,2}\.\d{2}|\b(ноя|дек)", text, re.I)


@pytest.mark.parametrize("city", REGIONS)
def test_region_description_unchanged(city: str, monkeypatch) -> None:
    text = search_description(_view(city))
    assert text.startswith("Расписание массового катания на неделю. ")
    monkeypatch.setattr(place_page, "_brief_on", lambda view: False)
    assert search_description(_view(city)) == text


def test_minsk_without_sessions_does_not_promise_a_weekly_schedule() -> None:
    view = _view("Минск")
    view.update(days=[], session_count=0, next_slot=None)
    assert search_description(view) == (
        "Каток для массового катания. Билеты онлайн. Центральный район, пр-т Победителей, 65, Минск."
    )


@pytest.mark.parametrize(
    ("city", "has_skate", "has_ohm", "nearby_early"),
    [
        ("Минск", False, False, True),
        ("Минск", True, False, False),
        ("Минск", False, True, False),
        ("Мозырь", False, False, False),
    ],
)
def test_nearby_moves_up_only_for_a_minsk_rink_without_sessions(
    city: str, has_skate: bool, has_ohm: bool, nearby_early: bool
) -> None:
    view = _view(city, ohm=has_ohm)
    if not has_skate:
        view.update(days=[], session_count=0, next_slot=None)
    href = "/p/minsk/alternative"
    view["nearby"] = [{"kind": "arena", "name": "Другой каток", "href": href, "line": "завтра в 12:00"}]

    html = _render(view)
    assert html.count(f'href="{href}"') == 1
    assert 'data-glide-track="es_fallback_click"' in html
    assert (html.index(f'href="{href}"') < html.index("Адрес и контакты")) is nearby_early
    if nearby_early:
        assert html.index('id="schedule"') < html.index(f'href="{href}"')
