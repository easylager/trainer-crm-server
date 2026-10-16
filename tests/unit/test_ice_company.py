"""Компания на лёд: тексты, флаг, лимитер, напоминания, callback. Без базы."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.application.ice_company.copy import Snap, card_text, confirm_dm, together_line
from src.application.ice_company.flag import city_enabled, enabled_city_ids
from src.application.ice_company.lifecycle import parse_callback, render_hash
from src.application.ice_company.limiter import OutboundLimiter
from src.application.ice_company.reminders import SKIPPED, plan
from src.application.ice_company.safety import TextRejected, callback_data, clean_free_text, escape_html, escape_markdown_v2
from src.shared.config import Settings

_MINSK = ZoneInfo("Europe/Minsk")


def _snap(**kwargs) -> Snap:
    base = dict(
        kind="public_skate",
        venue="Чижовка-Арена",
        starts_at=datetime(2026, 10, 17, 19, 0, tzinfo=_MINSK),
        min_people=3,
        status="open",
        going_names=("Аня",),
    )
    base.update(kwargs)
    return Snap(**base)


def test_card_matches_the_agreed_wording() -> None:
    assert card_text(_snap()) == (
        "Катаемся в субботу\nЧижовка-Арена, сб 19:00\nИдут 1 из 3: Аня\nНе хватает 2"
    )
    confirmed = _snap(status="confirmed", going_names=("Аня", "Макс", "Оля"))
    assert card_text(confirmed).split("\n", 1)[0] == "Едем. Идут 3: Аня, Макс, Оля"
    assert confirm_dm(confirmed) == "Сбор готов. Суббота, 19:00, Чижовка-Арена"


def test_flag_is_off_until_a_city_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ICE_COMPANY_CITY_IDS", "")
    assert enabled_city_ids(Settings()) == set()
    assert city_enabled(1, Settings()) is False
    monkeypatch.setenv("ICE_COMPANY_CITY_IDS", "12, 34")
    assert city_enabled(12, Settings()) is True
    assert city_enabled(99, Settings()) is False


def test_names_reject_links_and_escape() -> None:
    with pytest.raises(TextRejected):
        clean_free_text("https://evil.example", max_len=40, required=True, field="Имя")
    assert escape_html("<Аня>") == "&lt;Аня&gt;"
    assert escape_markdown_v2("а_б") == "а\\_б"


def test_callback_data_fits_telegram() -> None:
    data = callback_data("abcdefgh", "g")
    assert len(data.encode()) <= 64
    assert parse_callback(data) == ("abcdefgh", "g")
    assert parse_callback("ic:short:g") is None


def test_day_reminder_skipped_when_company_is_young() -> None:
    start = datetime(2026, 10, 17, 16, 0, tzinfo=timezone.utc)
    young = plan(created_at=start - timedelta(hours=5), starts_at=start, ends_at=start + timedelta(hours=1), weekly_in_chat=False)
    assert young[0][2] == SKIPPED
    early = plan(created_at=start - timedelta(days=3), starts_at=start, ends_at=start + timedelta(hours=1), weekly_in_chat=True)
    assert early[0][2] == "pending"
    assert early[-1][0] == "weekly"


def test_limiter_spaces_the_same_chat() -> None:
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    limiter = OutboundLimiter(global_per_sec=30, chat_per_sec=1, group_per_min=20, clock=clock)
    assert limiter.delay(5, is_group=False) == 0
    limiter.mark(5, is_group=False)
    assert limiter.delay(5, is_group=False) == pytest.approx(1)
    assert limiter.delay(6, is_group=False) == 0


def test_identical_card_hash_is_stable() -> None:
    buttons = [{"text": "Иду", "data": "ic:abcdefgh:g"}]
    assert render_hash("Едем", buttons) == render_hash("Едем", buttons)
    assert together_line(3) == "Вы катались вместе 3 раза"
    assert together_line(1) == "Вы катались вместе 1 раз"
