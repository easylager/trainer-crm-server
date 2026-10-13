"""TASK-250: один файл примеров для Python и JS (display_rules.json)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.application.ice_city_day import format_price_minor
from src.application.place_page import open_now_label
from src.shared.arena_schedule_mode import PHONE_LINE, season_closed_user_line
from src.shared.public_display import (
    format_clock,
    format_minor_amount,
    sentence_when,
    session_day_phrase,
    short_day_word,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "display_rules.json"


def _load_cases() -> tuple[date, list[dict]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    today = date.fromisoformat(str(payload["today"]))
    return today, list(payload["cases"])


def _run_case(case: dict, *, today: date) -> str:
    fn = case["fn"]
    args = case.get("args") or {}
    if fn == "format_clock":
        return format_clock(str(args.get("hhmm") or ""))
    if fn == "short_day_word":
        return short_day_word(date.fromisoformat(str(args["day"])), today=today)
    if fn == "session_day_phrase":
        return session_day_phrase(
            date.fromisoformat(str(args["day"])),
            str(args.get("hhmm") or ""),
            today=today,
        )
    if fn == "sentence_when":
        return sentence_when(
            date.fromisoformat(str(args["day"])),
            str(args.get("hhmm") or ""),
            today=today,
        )
    if fn == "format_minor_amount":
        minor = args.get("minor")
        return format_minor_amount(minor if minor is not None else None)
    if fn == "format_price_minor":
        minor = args.get("minor")
        return format_price_minor(minor if minor is not None else None, str(args.get("currency") or "BYN"))
    if fn == "open_status":
        card = {
            "opening_hours": args.get("opening_hours"),
            "timezone": str(args.get("timezone") or "Europe/Minsk"),
        }
        now = datetime.fromisoformat(str(args["now_utc"]))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("UTC"))
        return open_now_label(card, now=now)
    if fn == "schedule_phone_line":
        return PHONE_LINE
    if fn == "schedule_season_closed":
        reopen = args.get("reopen_date")
        reopen_date = date.fromisoformat(str(reopen)) if reopen else None
        note = args.get("note")
        return season_closed_user_line(reopen_date=reopen_date, note=str(note) if note else None)
    raise AssertionError(f"unknown fn {fn!r} in {case.get('id')}")


def test_display_rules_fixture() -> None:
    today, cases = _load_cases()
    assert len(cases) >= 40
    for case in cases:
        got = _run_case(case, today=today)
        assert got == case["expect"], f"{case.get('id')}: got {got!r}, want {case['expect']!r}"
