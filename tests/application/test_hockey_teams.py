"""TASK-299: справочник команд — окно календаря, контраст белого текста, неизвестная команда."""

from __future__ import annotations

from pathlib import Path

from src.application.hockey_teams import TEAMS, UNKNOWN_COLOR, team_card
from src.ingestion.hockey_sources import parse_hcdinamo_logo_index

FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/hockey"


def white_text_contrast(hex_color: str) -> float:
    """WCAG: яркость цвета против белого (#FFFFFF). Ниже 4.5 белый текст на половинке не читается."""
    raw = hex_color.removeprefix("#")
    red, green, blue = (int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
    return 1.05 / (luminance + 0.05)


def test_calendar_window_teams_have_short_name_color_and_logo() -> None:
    html = (FIXTURES / "hcdinamo-calendar.html").read_text(encoding="utf-8")
    names = set(parse_hcdinamo_logo_index(html))
    assert names, "в фикстуре календаря нет команд"
    for name in names:
        card = team_card(name)
        assert card["name"] == name
        assert card["short"] == TEAMS[name].short
        assert len(card["short"]) == 2
        assert card["logo"] == f"/static/webapp/hockey-logos/{TEAMS[name].slug}.png"
        assert white_text_contrast(card["color"]) >= 4.5


def test_known_club_colors_keep_white_text_readable() -> None:
    for name, team in TEAMS.items():
        assert white_text_contrast(team.color) >= 4.5, name
    assert white_text_contrast(UNKNOWN_COLOR) >= 4.5


def test_unknown_team_is_neutral_and_has_no_logo() -> None:
    card = team_card("Югра")
    assert card == {"name": "Югра", "short": "ЮГ", "color": UNKNOWN_COLOR, "logo": None}
    two = team_card("Новый Клуб")
    assert two["short"] == "НК"
    assert two["logo"] is None


def test_examples_from_the_brief() -> None:
    assert team_card("Динамо-Минск")["short"] == "ДМ"
    assert team_card("Барыс")["short"] == "БР"
    assert team_card("ХК Сочи")["short"] == "СЧ"
