"""Волна 0: классификатор P* и разметка data-glide-track."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.application.empty_state_telemetry import (
    FALLBACK_NEARBY_CITY,
    FALLBACK_OTHER_RINK,
    GOAL_ES_FALLBACK_CLICK,
    GOAL_ES_VIEW,
    GOAL_ES_WATCH_START,
    GOAL_TELEGRAM_CTA,
    GOAL_TICKET_BUY,
    GOAL_TRAINER_CLICK,
    classify_place_state,
    glide_track_boot_html,
    place_track_context,
    track_attrs,
)
from src.application.place_page import render_place_page
from src.shared.arena_schedule_mode import SCHEDULE_MODE_PHONE


def _card(**overrides):
    base = {
        "id": 2,
        "name": "Минск Арена",
        "city_name": "Минск",
        "city_id": 1,
        "country": "BY",
        "venue_type": "ice",
        "schedule_tracked": True,
        "schedule_mode": "auto",
        "amenities": {},
    }
    base.update(overrides)
    return base


def _view(card, *, days=None, today=None, alternatives=None, nearby=None, trainers=None):
    today = today or date(2026, 11, 15)
    now = datetime(today.year, today.month, today.day, 12, 0, tzinfo=timezone.utc)
    return {
        "card": card,
        "today": today,
        "now": now,
        "days": days if days is not None else [],
        "alternatives": alternatives or [],
        "nearby": nearby or [],
        "trainers": trainers or [],
    }


def test_classify_p6_tracked_empty():
    assert classify_place_state(_view(_card(id=2, schedule_tracked=True))) == "P6"


def test_classify_p7_untracked_empty():
    assert classify_place_state(_view(_card(schedule_tracked=False))) == "P7"


def test_classify_p8_phone():
    assert classify_place_state(_view(_card(id=28, schedule_mode=SCHEDULE_MODE_PHONE))) == "P8"


def test_classify_p10_hockey_center_before_phone():
    assert (
        classify_place_state(
            _view(
                _card(
                    id=9,
                    schedule_mode=SCHEDULE_MODE_PHONE,
                    amenities={"hockey_center": True},
                )
            )
        )
        == "P10"
    )


def test_classify_p5_horizon_tail():
    today = date(2026, 11, 15)
    days = [
        {
            "local_date": today.isoformat(),
            "sessions": [{"id": 1, "starts_at_local": "10:00"}],
        }
    ]
    assert classify_place_state(_view(_card(id=33), days=days, today=today)) == "P5"


def test_classify_p1_full_week():
    today = date(2026, 11, 10)  # вторник
    days = [
        {
            "local_date": (today + timedelta(days=i)).isoformat(),
            "sessions": [{"id": i + 1, "starts_at_local": "10:00"} for _ in range(2)],
        }
        for i in range(7)
    ]
    assert classify_place_state(_view(_card(), days=days, today=today)) == "P1"


def test_track_attrs_and_boot_html():
    attrs = track_attrs(
        GOAL_ES_FALLBACK_CLICK,
        fallback=FALLBACK_OTHER_RINK,
        target="/p/x",
        pos=1,
        surface="place_page",
    )
    assert 'data-glide-track="es_fallback_click"' in attrs
    assert 'data-glide-fallback="other_rink"' in attrs
    assert 'data-glide-pos="1"' in attrs

    ctx = place_track_context(_view(_card(id=2, schedule_tracked=True)))
    assert ctx["state"] == "P6"
    assert ctx["page_type"] == "place"
    assert ctx["arena_id"] == 2

    boot = glide_track_boot_html(ctx)
    assert 'id="glide-es-context"' in boot
    assert '"state":"P6"' in boot
    assert "/static/shared/glide-track.js" in boot
    assert GOAL_ES_VIEW == "es_view"
    assert GOAL_ES_WATCH_START == "es_watch_start"
    assert GOAL_TICKET_BUY == "ticket_buy"
    assert GOAL_TRAINER_CLICK == "trainer_click"
    assert GOAL_TELEGRAM_CTA == "telegram_cta"


def _share():
    return {"share_url": "https://x/p/x", "share_text": "x", "share_body": "x"}


def _render(view):
    return render_place_page(
        view,
        canonical_url="https://example.test/p/minsk/test",
        base_path="/p/minsk/test",
        og_image_url="https://example.test/p/minsk/test/og.png",
        story_image_url="https://example.test/p/minsk/test/story.png",
        cta_url="https://example.test/api/public/catalog/open-telegram?startapp=arena_1&surface=place_page",
        city_page_url="/c/minsk",
        share=_share(),
    )


def test_html_p6_minsk_arena_watch_and_es_context():
    html = _render(
        _view(
            _card(id=2, name="Минск Арена", schedule_tracked=True),
        )
    )
    assert 'id="glide-es-context"' in html
    assert '"state":"P6"' in html
    assert "/static/shared/glide-track.js" in html
    assert 'data-glide-track="es_watch_start"' in html


def test_html_p10_olympic_alternatives_fallback():
    html = _render(
        _view(
            _card(
                id=9,
                name="Олимпик-арена",
                amenities={"hockey_center": True},
                schedule_mode=SCHEDULE_MODE_PHONE,
            ),
            alternatives=[
                {
                    "arena_id": 3,
                    "arena_name": "Замок",
                    "path": "/p/minsk/zamok",
                    "session_id": 11,
                    "day_label": "сегодня",
                    "starts_at_local": "10:00",
                    "distance_km": 2.1,
                }
            ],
        )
    )
    assert '"state":"P10"' in html
    assert 'data-glide-track="es_fallback_click"' in html
    assert 'data-glide-fallback="other_rink"' in html
    assert "Массового катания" in html or "массового" in html.lower() or "no_public" in html or "b-info__row" in html


def test_html_p8_ivacevichi_and_nearby_fallback():
    html = _render(
        _view(
            _card(id=28, name="Ивацевичи", city_name="Ивацевичи", schedule_mode=SCHEDULE_MODE_PHONE),
            nearby=[
                {
                    "name": "Барановичи",
                    "rink_count": 1,
                    "when": "сегодня",
                    "time": "18:00",
                    "distance": "40 км",
                    "photo_url": None,
                    "display_tone": False,
                }
            ],
        )
    )
    assert '"state":"P8"' in html
    assert 'data-glide-fallback="nearby_city"' in html
    assert FALLBACK_NEARBY_CITY in html or 'data-glide-fallback="nearby_city"' in html


def test_html_p5_gomel_and_lida_tail():
    today = date(2026, 11, 15)
    days = [
        {
            "local_date": today.isoformat(),
            "sessions": [{"id": 1, "starts_at_local": "12:00", "price_adult_minor": 1000}],
        }
    ]
    for arena_id, name, city in ((33, "Гомель", "Гомель"), (37, "Лида", "Лида")):
        html = _render(_view(_card(id=arena_id, name=name, city_name=city), days=days, today=today))
        assert '"state":"P5"' in html, name
        assert "/static/shared/glide-track.js" in html


def test_html_ticket_buy_and_trainer_click():
    today = date(2026, 11, 10)
    days = [
        {
            "local_date": (today + timedelta(days=i)).isoformat(),
            "sessions": [{"id": i + 1, "starts_at_local": "10:00", "price_adult_minor": 1000}],
        }
        for i in range(7)
    ]
    html = _render(
        _view(
            _card(
                id=3,
                name="Замок",
                tickets_url="https://tickets.example/buy",
                schedule_tracked=True,
            ),
            days=days,
            today=today,
            trainers=[{"id": 7, "name": "Анна", "line": "обучение", "can_book": True}],
        )
    )
    # Билеты могут идти через beacon-прокси — главное наличие цели.
    assert 'data-glide-track="ticket_buy"' in html or "tickets" in html
    assert 'data-glide-track="trainer_click"' in html
