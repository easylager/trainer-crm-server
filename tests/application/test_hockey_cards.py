"""TASK-300: карточки «Кто кого» для чата — размер, длинные названия, подпись адреса."""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from src.application import hockey_cards as cards

_NAVY = (13, 20, 36)


def _image(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def _ink_columns(image: Image.Image, top: int, bottom: int, background: tuple[int, int, int]) -> list[int]:
    """Колонки, где в полосе [top, bottom) есть что-то кроме фона."""
    px = image.load()
    out = []
    for x in range(image.width):
        if any(px[x, y] != background for y in range(top, bottom, 2)):
            out.append(x)
    return out


def test_result_card_is_1200x630_and_only_for_points() -> None:
    png = cards.render_result_card(home="ХК Сочи", away="Динамо-Минск", home_score=2, away_score=3, points=50)
    assert _image(png).size == cards.CARD_SIZE == (1200, 630)
    winner = cards.render_result_card(
        home="Шанхайские Драконы", away="Динамо-Минск", home_score=4, away_score=3, points=20
    )
    assert _image(winner).size == (1200, 630)
    with pytest.raises(ValueError):
        cards.render_result_card(home="А", away="Б", home_score=1, away_score=0, points=10)


@pytest.mark.parametrize(
    "name",
    ["Пятничный ОХМ", "Хоккейные пенсионеры Уручья", "Суперлигачемпионовминскаяхх", "Офис на льду и немного дворa"],
)
def test_league_card_long_names_fill_the_line_and_never_overflow(name: str) -> None:
    image = _image(cards.render_league_card(name=name, members=8, names=list("ЛКСИВД"), next_match=None))
    assert image.size == (1200, 630)
    # Полоса названия: между подписью «кто кого · лига» и кружками участников.
    ink = _ink_columns(image, 112, 330, _NAVY)
    assert ink, "название не нарисовано"
    assert max(ink) <= 1200 - 72 + 2, "название вылезло за поле"
    if len(name) > 12:
        assert max(ink) >= 0.6 * 1200, "длинное название оставило пустое поле справа"


def test_league_card_without_next_match_and_single_member() -> None:
    png = cards.render_league_card(name="Двор", members=1, names=["Максим"], next_match=None)
    assert _image(png).size == (1200, 630)


def test_people_label_and_match_when() -> None:
    assert cards.people_label(1) == "уже 1 человек"
    assert cards.people_label(3) == "уже 3 человека"
    assert cards.people_label(12) == "уже 12 человек"
    assert cards.people_label(22) == "уже 22 человека"
    # 24.10.2026 — суббота; 14:00 UTC = 17:00 в Минске.
    assert cards.match_when(datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)) == "сб 24.10, 17:00"


def test_result_card_signature() -> None:
    sig = cards.result_card_sig("token", 42, 5)
    assert cards.check_result_card_sig("token", 42, 5, sig)
    assert not cards.check_result_card_sig("token", 42, 1, sig)
    assert not cards.check_result_card_sig("other", 42, 5, sig)
    assert not cards.check_result_card_sig("token", 42, 5, "")


def test_league_card_version_follows_content() -> None:
    a = cards.league_card_version("Двор", 3, ["А", "Б"], None)
    assert a == cards.league_card_version("Двор", 3, ["А", "Б"], None)
    assert a != cards.league_card_version("Двор", 4, ["А", "Б"], None)
    assert a != cards.league_card_version("Двор", 3, ["А", "Б"], "Торпедо — Динамо-Минск, сб 24.10, 17:00")


def test_captions() -> None:
    assert (
        cards.result_caption(home="ХК Сочи", away="Динамо-Минск", home_score=2, away_score=3, points=50)
        == "Кто кого: в точку! ХК Сочи — Динамо-Минск 2:3, +50"
    )
    assert "«Двор»" in cards.league_caption("Двор")
