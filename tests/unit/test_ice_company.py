"""Компания на лёд: тексты, флаг, лимитер, напоминания, callback. Без базы."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.application.ice_company.copy import Snap, card_text, confirm_dm, kind_label, together_line
from src.application.ice_company.flag import city_enabled, enabled_city_ids
from src.application.ice_company.copy import team_gathered
from src.application.ice_company.lifecycle import button_rows, buttons_for, parse_callback, render_hash
from src.application.ice_company.service import ice_slot_url
from src.application.ice_company.limiter import OutboundLimiter
from src.application.ice_company.reminders import SKIPPED, plan
from src.application.ice_company.safety import (
    TextRejected,
    callback_data,
    clean_free_text,
    escape_html,
    escape_markdown_v2,
    strip_emoji_for_poster,
)
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


def test_poster_is_a_rink() -> None:
    import io

    from PIL import Image

    from src.application.ice_company.og import render_company_card

    raw = render_company_card(_snap(going_names=("Аня", "Макс"), min_people=4))
    assert raw.startswith(b"\x89PNG")
    image = Image.open(io.BytesIO(raw))
    assert image.size == (1080, 1080)
    # Ночной угол и светлый лёд посередине площадки.
    assert image.getpixel((12, 12))[0] < 40
    ice = image.getpixel((180, 520))
    assert ice[2] > 180 and ice[0] > 160


def test_card_matches_the_agreed_wording() -> None:
    assert card_text(_snap()) == (
        "Массовое катание\nСуббота, 19:00\nЧижовка-Арена\nНа льду Аня.\nЕщё двое — и едем"
    )
    confirmed = _snap(status="confirmed", going_names=("Аня", "Макс", "Оля"))
    assert card_text(confirmed).split("\n", 1)[0] == "Массовое катание"
    assert "Едем." in card_text(confirmed)
    assert "На льду Аня, Макс и Оля." in card_text(confirmed)
    assert confirm_dm(confirmed) == "Сбор готов. Суббота, 19:00, Чижовка-Арена"
    assert kind_label("hockey_practice") == "ОХМ"
    assert card_text(_snap(kind="hockey_practice")).startswith("ОХМ\n")


def test_flag_is_off_until_a_city_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ICE_COMPANY_CITY_IDS", "")
    assert enabled_city_ids(Settings()) == set()
    assert city_enabled(1, Settings()) is False
    monkeypatch.setenv("ICE_COMPANY_CITY_IDS", "12, 34")
    assert city_enabled(12, Settings()) is True
    assert city_enabled(99, Settings()) is False


def test_poster_strips_emoji_from_names() -> None:
    from src.application.ice_company.og import render_company_card

    assert strip_emoji_for_poster("Максим 🏒") == "Максим"
    assert strip_emoji_for_poster("🔥 только огонь") == "только огонь"
    raw = render_company_card(_snap(going_names=("Максим 🏒",), min_people=1))
    assert raw.startswith(b"\x89PNG")


def test_names_reject_links_and_escape() -> None:
    with pytest.raises(TextRejected):
        clean_free_text("https://evil.example", max_len=40, required=True, field="Имя")
    assert clean_free_text("Котлеты на ребро 🧊", max_len=48, required=True, field="Имя") == "Котлеты на ребро 🧊"
    with pytest.raises(TextRejected):
        clean_free_text("<script>", max_len=40, required=True, field="Имя")
    assert escape_html("<Аня>") == "&lt;Аня&gt;"
    assert escape_markdown_v2("а_б") == "а\\_б"


def test_team_title_on_card_caption() -> None:
    snap = _snap(team_title="Пивной Олимп")
    assert card_text(snap).startswith("Массовое катание\nПивной Олимп\n")


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


def test_on_ice_opens_the_arena_slot() -> None:
    company = {
        "public_code": "abcdefgh",
        "venue_ref": "arena:42",
        "source_ref": "ice_session:9001",
    }
    settings = Settings(
        webapp_base_url="https://glide.example",
        client_bot_username="glidebot",
        client_bot_main_mini_app=True,
    )
    url = ice_slot_url(company, settings)
    assert url == "https://t.me/glidebot?startapp=arena_42_s_9001"
    snap = _snap()
    buttons = buttons_for(company, snap, url)
    assert buttons[-1] == {"text": "На лёд", "url": url}
    assert buttons[0] == {"text": "Иду", "data": "ic:abcdefgh:g", "style": "primary"}
    assert buttons[1] == {"text": "Не могу", "data": "ic:abcdefgh:x", "style": "danger"}
    assert buttons[2] == {"text": "В другой чат →", "switch_inline": "k:abcdefgh"}
    assert button_rows(buttons) == [[buttons[0]], [buttons[1]], [buttons[2]], [buttons[3]]]


def test_ticket_buttons_when_team_gathered() -> None:
    company = {"public_code": "abcdefgh"}
    url = "https://t.me/glidebot?startapp=arena_1"
    ics = "https://glide.example/k/abcdefgh/event.ics"
    snap = _snap(status="confirmed", going_names=("Аня", "Макс", "Оля"), min_people=3)
    assert team_gathered(snap)
    buttons = buttons_for(company, snap, url, calendar_url=ics)
    assert [b["text"] for b in buttons] == ["В календарь", "На лёд", "В другой чат →"]
    assert buttons[0]["url"] == ics


def test_poster_renders_gathered_tagline() -> None:
    from src.application.ice_company.og import render_company_card

    raw = render_company_card(
        _snap(status="confirmed", going_names=("Аня", "Макс", "Оля"), min_people=3),
    )
    assert raw.startswith(b"\x89PNG")


def test_poster_pastes_avatar_on_ice() -> None:
    import io

    from PIL import Image

    from src.application.ice_company.og import render_company_card

    face = Image.new("RGB", (64, 64), (220, 40, 40))
    buf = io.BytesIO()
    face.save(buf, format="JPEG")
    raw = render_company_card(
        _snap(going_names=("Аня",), min_people=3),
        avatar_bytes=[buf.getvalue()],
    )
    assert raw.startswith(b"\x89PNG")


def test_identical_card_hash_is_stable() -> None:
    buttons = [{"text": "Иду", "data": "ic:abcdefgh:g"}]
    assert render_hash("Едем", buttons) == render_hash("Едем", buttons)
    assert together_line(3) == "Вы катались вместе 3 раза"
    assert together_line(1) == "Вы катались вместе 1 раз"
