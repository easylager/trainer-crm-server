"""Компания на лёд: тексты, флаг, лимитер, callback. Без базы."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.application.ice_company.copy import Snap, card_text, closed_headline, crowd_line, kind_label
from src.application.ice_company.flag import city_enabled, enabled_city_ids
from src.application.ice_company.lifecycle import button_rows, buttons_for, parse_callback, render_hash
from src.application.ice_company.service import ice_slot_url
from src.application.ice_company.limiter import OutboundLimiter
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
        status="open",
        going_names=("Аня",),
    )
    base.update(kwargs)
    return Snap(**base)


def test_crowd_line_ladder() -> None:
    assert crowd_line(0) == "Лёд пока пустой"
    assert crowd_line(1) == "Пока один. Одному можно, но вдвоём веселее"
    assert crowd_line(2) == "Двое — это уже не катание, а свидание"
    assert crowd_line(3) == "Трое — это уже компания"
    assert crowd_line(4) == "Четверо — можно два на два"
    assert crowd_line(5) == "Пятеро — готовая хоккейная пятёрка"
    assert crowd_line(6) == "Шестеро — пятёрка и вратарь"
    assert crowd_line(7) == "Семеро — каток, считай, ваш"
    assert crowd_line(8) == "Восьмеро — каток, считай, ваш"
    assert crowd_line(9) == "Девятеро — каток, считай, ваш"
    assert crowd_line(10) == "10 человек — это уже не компания, а выезд"
    assert crowd_line(12) == "12 человек — это уже не компания, а выезд"


def test_closed_headlines() -> None:
    assert closed_headline(_snap(session_cancelled=True)) == "Сеанс сняли"
    assert closed_headline(_snap(status="cancelled")) == "Сбор снят"
    assert closed_headline(_snap(expired=True, status="expired", going_names=("Аня",))) == "Сеанс прошёл"
    assert closed_headline(_snap(expired=True, status="expired", going_names=("Аня", "Макс"))) == "Покатались"


def test_card_matches_core_wording() -> None:
    assert card_text(_snap()) == (
        "Массовое катание\n"
        "Суббота, 19:00\n"
        "Чижовка-Арена\n"
        "На льду Аня.\n"
        "Пока один. Одному можно, но вдвоём веселее"
    )
    assert kind_label("hockey_practice") == "ОХМ"
    assert card_text(_snap(kind="hockey_practice")).startswith("ОХМ\n")


def test_poster_is_a_rink() -> None:
    import io

    from PIL import Image

    from src.application.ice_company.og import render_company_card

    raw = render_company_card(_snap(going_names=("Аня", "Макс")))
    assert raw.startswith(b"\x89PNG")
    image = Image.open(io.BytesIO(raw))
    assert image.size == (1080, 1080)
    assert image.getpixel((12, 12))[0] < 40
    # Тёмный лист катка, как обложки сайта, и бирюзовая центральная линия.
    from src.application.ice_company.og import _RINK_MID, _SHEET

    assert image.getpixel((180, 600))[:3] == _SHEET
    assert image.getpixel((540, 760))[:3] == _RINK_MID


def test_poster_renders_for_going_counts() -> None:
    from src.application.ice_company.og import render_company_card

    for names in ((), ("Аня",), ("Аня", "Макс"), ("А", "Б", "В"), tuple(f"U{i}" for i in range(6)), tuple(f"U{i}" for i in range(12))):
        raw = render_company_card(_snap(going_names=names))
        assert raw.startswith(b"\x89PNG")


def test_poster_team_titles() -> None:
    from src.application.ice_company.og import render_company_card

    assert render_company_card(_snap(going_names=())).startswith(b"\x89PNG")
    assert render_company_card(_snap(team_title="Пивной Олимп")).startswith(b"\x89PNG")
    long_title = "А" * 40
    assert render_company_card(_snap(team_title=long_title, going_names=("Аня",))).startswith(b"\x89PNG")
    assert render_company_card(_snap(team_title="Команда 🏒🔥", going_names=("Макс",))).startswith(b"\x89PNG")


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
    raw = render_company_card(_snap(going_names=("Максим 🏒",)))
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
    assert parse_callback("ic:abcdefgh:q") is None


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


def test_poster_pastes_avatar_on_ice() -> None:
    import io

    from PIL import Image

    from src.application.ice_company.og import render_company_card

    face = Image.new("RGB", (64, 64), (220, 40, 40))
    buf = io.BytesIO()
    face.save(buf, format="JPEG")
    raw = render_company_card(
        _snap(going_names=("Аня",)),
        avatar_bytes=[buf.getvalue()],
    )
    assert raw.startswith(b"\x89PNG")


def test_identical_card_hash_is_stable() -> None:
    buttons = [{"text": "Иду", "data": "ic:abcdefgh:g"}]
    assert render_hash("Едем", buttons) == render_hash("Едем", buttons)


def test_match_card_text_and_toasts() -> None:
    from src.application.ice_company.copy import match_when, toast_for

    friday = datetime(2026, 10, 23, 19, 30, tzinfo=_MINSK)
    assert match_when(friday) == "пт, 23 октября, 19:30"
    snap = _snap(
        kind="hockey_match",
        venue="Минск-Арена",
        starts_at=friday,
        team_title="Динамо-Минск — СКА",
        going_names=("Макс", "Аня"),
        maybe_names=("Дима",),
    )
    assert card_text(snap) == (
        "Идём на матч?\n"
        "Динамо-Минск — СКА · пт, 23 октября, 19:30 · Минск-Арена\n"
        "Идут: Макс, Аня · Смотрит дома: Дима"
    )
    assert card_text(_snap(kind="hockey_match", venue="Минск-Арена", starts_at=friday, going_names=())).count("\n") == 1
    assert closed_headline(_snap(kind="hockey_match", expired=True, status="expired")) == "Матч прошёл"
    assert closed_headline(_snap(kind="hockey_match", session_cancelled=True)) == "Матч отменён"
    assert toast_for("hockey_match", "m") == "Записали, смотришь дома"
    assert toast_for("public_skate", "m") == "Записали, может быть"
    assert toast_for("hockey_match", "x") == toast_for("public_skate", "x") == "Записали, не идёшь"
    many = _snap(kind="hockey_match", going_names=tuple(f"Игрок{i}" for i in range(7)))
    assert "Идут: Игрок0, Игрок1, Игрок2, Игрок3 и ещё 3" in card_text(many)
