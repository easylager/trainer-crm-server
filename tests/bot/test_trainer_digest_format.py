"""Unit tests for trainer digest Telegram renderer. No DB.

Design assertions target behavior + Product-voice invariants, not exact copywriting.
If we tweak wording, we shouldn't have to touch every test — only the visual-signature
(emoji hero), structure (sections/bullets), and the presence of the single 👉 recommendation.
"""
from datetime import date, time, timedelta

import pytest

from src.bot.trainer_digest_format import (
    _bookings_word,
    _format_duration_minutes,
    _format_money_cents,
    _plural_ru,
    _requests_word,
    _sessions_word,
    _short_client_name,
    format_morning_digest,
    format_morning_digest_lite_owed_only,
    format_weekly_digest,
)


# =============================================================================
# Helper tests — plural rules
# =============================================================================


@pytest.mark.parametrize(
    "n,expected",
    [
        (1, "тренировка"),
        (2, "тренировки"),
        (3, "тренировки"),
        (4, "тренировки"),
        (5, "тренировок"),
        (11, "тренировок"),
        (12, "тренировок"),
        (21, "тренировка"),
        (22, "тренировки"),
        (25, "тренировок"),
        (101, "тренировка"),
        (111, "тренировок"),
    ],
)
def test_sessions_plural_rules(n: int, expected: str) -> None:
    assert _sessions_word(n) == expected


def test_plural_ru_reusable() -> None:
    assert _plural_ru(1, "x", "y", "z") == "x"
    assert _plural_ru(3, "x", "y", "z") == "y"
    assert _plural_ru(11, "x", "y", "z") == "z"


def test_requests_and_bookings_words() -> None:
    assert _requests_word(1) == "заявка"
    assert _requests_word(5) == "заявок"
    assert _bookings_word(2) == "записи"


# =============================================================================
# Helper tests — formatters
# =============================================================================


@pytest.mark.parametrize(
    "minutes,expected",
    [
        (0, "0м"),
        (45, "45м"),
        (60, "1ч"),
        (90, "1ч 30м"),
        (120, "2ч"),
        (390, "6ч 30м"),
        (-10, "0м"),
    ],
)
def test_duration_formatting(minutes: int, expected: str) -> None:
    assert _format_duration_minutes(minutes) == expected


@pytest.mark.parametrize(
    "cents,expected",
    [
        (0, "0 BYN"),
        (100, "1 BYN"),
        (6000, "60 BYN"),
        (6050, "60,50 BYN"),
        (6099, "60,99 BYN"),
    ],
)
def test_money_formatting(cents: int, expected: str) -> None:
    assert _format_money_cents(cents) == expected


@pytest.mark.parametrize(
    "full,short",
    [
        ("Ирина Ковалёва", "Ирина К."),
        ("Катя", "Катя"),
        ("", "Клиент"),
        ("  Олег   Петров  ", "Олег П."),
    ],
)
def test_short_name(full: str, short: str) -> None:
    assert _short_client_name(full) == short


# =============================================================================
# Morning digest
# =============================================================================


def _session(
    *,
    hh: int,
    mm: int = 0,
    name: str = "Олег Петров",
    arena: str | None = "Минск-Арена",
    first: bool = False,
    status: str = "confirmed",
    duration_min: int = 60,
) -> dict:
    start = time(hh, mm)
    end_total = hh * 60 + mm + duration_min
    end = time(end_total // 60, end_total % 60)
    return {
        "start_time": start,
        "end_time": end,
        "client_name": name,
        "arena_name": arena,
        "is_first_time": first,
        "status": status,
    }


def _morning_digest_fixture(sessions: list[dict], **overrides) -> dict:
    base = {
        "sessions": sessions,
        "sessions_count": len(sessions),
        "gaps": [],
        "first_timers_count": sum(1 for s in sessions if s.get("is_first_time")),
        "pending_confirmations_count": 0,
        "pending_requests_count": 0,
    }
    base.update(overrides)
    return base


def test_morning_digest_raises_on_empty_sessions() -> None:
    with pytest.raises(ValueError):
        format_morning_digest({"sessions": [], "sessions_count": 0})


def test_morning_digest_has_hero_emoji_and_count() -> None:
    """Hero line must carry the morning signature (☀️) so trainer recognizes the message instantly."""
    d = _morning_digest_fixture([_session(hh=9)])
    out = format_morning_digest(d)
    assert "☀️" in out
    assert "одна тренировка" in out
    assert "<b>09:00</b>" in out
    assert "Олег П." in out
    assert "Минск-Арена" in out


def test_morning_digest_greeting_follows_wall_time_for_manual_send_hour() -> None:
    d = _morning_digest_fixture([_session(hh=9)])
    assert "Доброе утро" in format_morning_digest(d, wall_time=time(8, 0))
    assert "Добрый день" in format_morning_digest(d, wall_time=time(15, 59))
    assert "Добрый вечер" in format_morning_digest(d, wall_time=time(18, 0))


def test_morning_digest_multiple_sessions_header_and_run_sheet() -> None:
    d = _morning_digest_fixture(
        [
            _session(hh=9, name="Олег Петров"),
            _session(hh=11, name="Ирина Ковалёва", first=True),
        ]
    )
    out = format_morning_digest(d)
    assert "<b>2</b> тренировки" in out
    assert "первая в <b>09:00</b>" in out
    assert "👋 первая тренировка" in out


def test_morning_digest_pending_session_gets_risk_tag() -> None:
    """Pending bookings must surface inline on the row so the trainer sees the risk."""
    d = _morning_digest_fixture([_session(hh=18, name="Катя С.", status="pending")])
    out = format_morning_digest(d)
    assert "⚠" in out
    assert "ждёт подтверждения" in out


def test_morning_digest_skips_arena_when_none() -> None:
    d = _morning_digest_fixture([_session(hh=9, name="Катя", arena=None)])
    out = format_morning_digest(d)
    row = next(line for line in out.split("\n") if line.startswith("<b>09:00"))
    assert row.count("·") == 1  # only "HH:MM · Катя", no arena


def test_morning_digest_surfaces_longest_gap_only() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="A", arena=None)],
        gaps=[
            {"from_time": time(10, 0), "to_time": time(12, 30), "duration_minutes": 150},
            {"from_time": time(13, 0), "to_time": time(18, 0), "duration_minutes": 300},
        ],
    )
    out = format_morning_digest(d)
    assert "13:00" in out and "18:00" in out and "5ч" in out
    assert "10:00" not in out  # shorter gap not rendered


def test_morning_digest_owed_line_requests_only() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="A", arena=None)],
        pending_requests_count=3,
    )
    out = format_morning_digest(d)
    assert "<b>3</b> заявки в каталоге" in out
    assert "на подтверждение" not in out


def test_morning_digest_owed_line_both_buckets() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="A", arena=None)],
        pending_requests_count=2,
        pending_confirmations_count=1,
    )
    out = format_morning_digest(d)
    assert "<b>2</b> заявки в каталоге" in out
    assert "<b>1</b> запись на подтверждение" in out


def test_morning_digest_no_owed_line_when_zero() -> None:
    d = _morning_digest_fixture([_session(hh=9, name="A", arena=None)])
    out = format_morning_digest(d)
    assert "Ждут" not in out


def test_morning_digest_always_closes_with_single_recommendation() -> None:
    """Every morning digest must end with exactly one 👉 line — the open-loop closer."""
    d = _morning_digest_fixture([_session(hh=9, name="A", arena=None)])
    out = format_morning_digest(d)
    assert out.count("👉") == 1
    assert out.rstrip().split("\n")[-1].startswith("👉")


def test_morning_recommendation_prefers_first_timer() -> None:
    """Highest retention leverage: greet the first-timer. Wins over pending/requests."""
    d = _morning_digest_fixture(
        [
            _session(hh=9, name="Олег Петров", status="pending"),
            _session(hh=11, name="Ирина Ковалёва", first=True),
        ],
        pending_requests_count=5,
    )
    out = format_morning_digest(d)
    rec = out.rstrip().split("\n")[-1]
    assert "Ирина К." in rec
    assert "первое" in rec or "впервые" in rec or "Первые минуты" in rec


def test_morning_recommendation_prefers_pending_confirm_over_requests() -> None:
    """After first-timer, bounded risk (specific pending booking) > generic owed requests."""
    d = _morning_digest_fixture(
        [_session(hh=18, name="Катя Смирнова", status="pending")],
        pending_requests_count=3,
    )
    out = format_morning_digest(d)
    rec = out.rstrip().split("\n")[-1]
    assert "Катя С." in rec
    assert "18:00" in rec


def test_morning_recommendation_falls_back_to_all_clear() -> None:
    d = _morning_digest_fixture([_session(hh=9, name="A", arena=None)])
    out = format_morning_digest(d)
    rec = out.rstrip().split("\n")[-1]
    assert "День собран" in rec or "Хорошей работы" in rec


def test_morning_digest_html_escapes_client_name() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="<script>alert(1)</script>", arena=None)]
    )
    out = format_morning_digest(d)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# =============================================================================
# Morning lite (0 sessions but owed requests)
# =============================================================================


def test_morning_lite_returns_none_when_no_owed_work() -> None:
    assert format_morning_digest_lite_owed_only({"pending_requests_count": 0}) is None
    assert format_morning_digest_lite_owed_only({}) is None


def test_morning_lite_has_hero_and_closes_with_recommendation() -> None:
    out = format_morning_digest_lite_owed_only({"pending_requests_count": 2})
    assert out is not None
    assert "☀️" in out
    assert "<b>2</b> заявки" in out
    assert "👉" in out


def test_morning_digest_includes_catalog_pulse_favorites_and_clicks() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="A", arena=None)],
        catalog_pulse={"favorites": 2, "contact_clicks": 1, "profile_views_total": 50},
    )
    out = format_morning_digest(d)
    assert "📈" in out
    assert "избранное" in out
    assert "Telegram" in out


def test_morning_digest_catalog_pulse_fallback_lifetime_views() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="A", arena=None)],
        catalog_pulse={"favorites": 0, "contact_clicks": 0, "profile_views_total": 12},
    )
    out = format_morning_digest(d)
    assert "📈" in out
    assert "12" in out
    assert "всего" in out
    assert "добавлений в избранное" not in out


def test_morning_digest_no_catalog_line_when_all_zero() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="A", arena=None)],
        catalog_pulse={"favorites": 0, "contact_clicks": 0, "profile_views_total": 0},
    )
    out = format_morning_digest(d)
    assert "📈" not in out


def test_morning_digest_omits_pulse_without_catalog_key() -> None:
    d = _morning_digest_fixture([_session(hh=9, name="A", arena=None)])
    out = format_morning_digest(d)
    assert "📈" not in out


def test_morning_digest_catalog_favorites_only() -> None:
    d = _morning_digest_fixture(
        [_session(hh=9, name="A", arena=None)],
        catalog_pulse={"favorites": 1, "contact_clicks": 0, "profile_views_total": 1},
    )
    out = format_morning_digest(d)
    assert "добавление в избранное" in out
    assert "Telegram" not in out


def test_morning_lite_includes_catalog_pulse() -> None:
    out = format_morning_digest_lite_owed_only(
        {
            "pending_requests_count": 2,
            "catalog_pulse": {"favorites": 1, "contact_clicks": 0, "profile_views_total": 0},
        }
    )
    assert out is not None
    assert "📈" in out
    assert "заявки" in out


# =============================================================================
# Weekly digest
# =============================================================================


def _weekly_fixture(**overrides) -> dict:
    today = date.today()
    base = {
        "past_week": {
            "completed_count": 0,
            "cash_cents": 0,
            "pass_sessions_count": 0,
            "cert_cents": 0,
        },
        "upcoming_week": {
            "sessions_count": 0,
            "empty_days": [today + timedelta(days=i) for i in range(1, 8)],
            "heaviest_day": None,
            "new_clients": [],
        },
        "drought": {"triggered": False},
    }
    base.update(overrides)
    return base


def test_weekly_has_sunday_hero_emoji() -> None:
    out = format_weekly_digest(_weekly_fixture())
    assert "🌙" in out


def test_weekly_digest_catalog_pulse_uses_week_scope() -> None:
    out = format_weekly_digest(
        _weekly_fixture(
            catalog_pulse={"favorites": 3, "contact_clicks": 2, "profile_views_total": 0},
        )
    )
    assert "📈" in out
    assert "прошлую неделю" in out.lower()


def test_weekly_digest_catalog_fallback_views_no_week_phrase_in_fallback() -> None:
    out = format_weekly_digest(
        _weekly_fixture(
            catalog_pulse={"favorites": 0, "contact_clicks": 0, "profile_views_total": 8},
        )
    )
    assert "📈" in out
    assert "8" in out
    assert "всего" in out


def test_weekly_has_both_section_headers() -> None:
    """Visual hierarchy: past ledger (📊) + forward view (📅) must be present even when empty."""
    out = format_weekly_digest(_weekly_fixture())
    assert "📊" in out
    assert "📅" in out
    assert "За прошедшую неделю" in out
    assert "Впереди" in out


def test_weekly_empty_past_and_future() -> None:
    out = format_weekly_digest(_weekly_fixture())
    assert "без тренировок" in out  # past empty
    assert "Неделя пока пустая" in out  # upcoming empty


def test_weekly_past_cash_only_renders_completed_and_cash_bullets() -> None:
    out = format_weekly_digest(
        _weekly_fixture(
            past_week={
                "completed_count": 5,
                "cash_cents": 25000,
                "pass_sessions_count": 0,
                "cert_cents": 0,
            }
        )
    )
    assert "<b>5</b> тренировок" in out
    assert "<b>250 BYN</b> наличными" in out


def test_weekly_past_mixed_cash_and_pass_and_cert() -> None:
    out = format_weekly_digest(
        _weekly_fixture(
            past_week={
                "completed_count": 8,
                "cash_cents": 24000,
                "pass_sessions_count": 3,
                "cert_cents": 5000,
            }
        )
    )
    assert "<b>240 BYN</b> наличными" in out
    assert "<b>3</b> тренировки по абонементам" in out
    assert "<b>50 BYN</b> по сертификатам" in out


def test_weekly_upcoming_with_heaviest_day_only_when_3plus() -> None:
    today = date.today()
    out = format_weekly_digest(
        _weekly_fixture(
            upcoming_week={
                "sessions_count": 2,
                "empty_days": [today + timedelta(days=i) for i in (2, 3, 4, 5, 6)],
                "heaviest_day": {"date": today + timedelta(days=1), "count": 2},
                "new_clients": [],
            }
        )
    )
    assert "Самый плотный" not in out  # below threshold


def test_weekly_upcoming_heaviest_day_surfaces_at_threshold() -> None:
    today = date.today()
    out = format_weekly_digest(
        _weekly_fixture(
            upcoming_week={
                "sessions_count": 6,
                "empty_days": [],
                "heaviest_day": {"date": today + timedelta(days=2), "count": 3},
                "new_clients": [],
            }
        )
    )
    assert "Самый плотный" in out


def test_weekly_drought_open_requests_line() -> None:
    out = format_weekly_digest(
        _weekly_fixture(
            drought={"triggered": True, "case": 1, "data": {"open_requests_count": 4}}
        )
    )
    assert "тебя ждут <b>4</b> заявки в каталоге" in out


def test_weekly_drought_case_7_silence() -> None:
    """Case 7 = nothing honest to say; no drought nudge should appear."""
    out = format_weekly_digest(
        _weekly_fixture(drought={"triggered": True, "case": 7, "data": {}})
    )
    assert "💬 На неделе" not in out
    assert "👁 На неделе" not in out


def test_weekly_always_closes_with_single_recommendation() -> None:
    out = format_weekly_digest(_weekly_fixture())
    assert out.count("👉") == 1
    assert out.rstrip().split("\n")[-1].startswith("👉")


def test_weekly_recommendation_surfaces_empty_day_on_non_empty_week() -> None:
    today = date.today()
    # Ensure exactly one empty day, and it's Friday (weekday=4 → 'пятницу' in accusative).
    # Pick the next Friday relative to today so the test is deterministic regardless of today.
    days_until_friday = (4 - today.weekday()) % 7 or 7
    friday = today + timedelta(days=days_until_friday)
    out = format_weekly_digest(
        _weekly_fixture(
            upcoming_week={
                "sessions_count": 6,
                "empty_days": [friday],
                "heaviest_day": None,
                "new_clients": [],
            }
        )
    )
    rec = out.rstrip().split("\n")[-1]
    assert "пятницу" in rec.lower()


def test_weekly_recommendation_mentions_heavy_day_when_4plus_sessions() -> None:
    today = date.today()
    heavy = today + timedelta(days=2)
    out = format_weekly_digest(
        _weekly_fixture(
            upcoming_week={
                "sessions_count": 5,
                "empty_days": [],
                "heaviest_day": {"date": heavy, "count": 4},
                "new_clients": [],
            }
        )
    )
    rec = out.rstrip().split("\n")[-1]
    assert "плотно" in rec
