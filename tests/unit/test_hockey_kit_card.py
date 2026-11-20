"""Карточка экипировки (TASK-432): разбор путей SVG, подпись, картинка без сбоев для всех вещей."""

from __future__ import annotations

from src.application.hockey_kit_card import (
    PHRASES,
    check_outfit_card_sig,
    outfit_caption,
    outfit_card_sig,
    paint_item,
    parse_path,
    render_outfit_card,
    shapes,
)
from src.application.hockey_league_captain import OUTFIT_WORDS, OUTFITS


def test_every_item_has_words_phrase_and_shape() -> None:
    assert set(OUTFITS) == set(PHRASES) == set(OUTFIT_WORDS) == set(shapes()) - {"cap"}


def test_path_parser_closes_subpaths_and_handles_relative_arc() -> None:
    subs = parse_path("M10 10 L20 10 L20 20 Z M30 30 H40 V40 Z")
    assert [closed for _, closed in subs] == [True, True]
    assert subs[1][0][:3] == [(30.0, 30.0), (40.0, 30.0), (40.0, 40.0)]
    arc = parse_path("M92 52 V2 a7 7 0 0 1 14 0 V6")[0][0]
    assert abs(arc[-2][0] - 106) < 1e-6 and abs(arc[-2][1] - 2) < 1e-6  # дуга кончается в (106, 2)


def test_every_item_paints_something() -> None:
    for item in shapes():
        layer = paint_item(item, size=80, stat="ЗА 0 ИЗ 4", score="1:2")
        assert layer.getbbox() is not None, item


def test_card_png_and_caption() -> None:
    png = render_outfit_card(name="Константин Константинопольский", item="bucket", stat="ЗА 1 ИЗ 4", score="2:3")
    assert png[:4] == b"\x89PNG"
    assert outfit_caption(name="Олег", item="wanted", stat="ЗА 0 ИЗ 4") == (
        "КТО КОГО: Олег разыскивается — за 0 из 4. Капитан лиги постарался — до следующего вечера."
    )
    sig = outfit_card_sig("t", 1, "261116", "abc", "bag")
    assert check_outfit_card_sig("t", 1, "261116", "abc", "bag", sig)
    assert not check_outfit_card_sig("t", 1, "261116", "abc", "bucket", sig)


def test_server_texts_match_the_mini_app_collection() -> None:
    import re
    from pathlib import Path

    from src.application.hockey_league_captain import OUTFIT_JOKES, OUTFIT_PHRASES

    src = Path("static/webapp/kto-kogo-kit.js").read_text(encoding="utf-8")
    head = r"\{ id: '(\w+)', as: '([^']*)', (?:asMe: '[^']*', )?of: '[^']*', name: '[^']*', full: '([^']*)', joke: '([^']*)' \}"
    rows = re.findall(head, src)
    assert {k: joke for k, _, _, joke in rows} == OUTFIT_JOKES
    # Заголовок «Саша в маске с трубкой» в Mini App — та же форма, что на картинке для чата.
    assert {k: phrase for k, phrase, _, _ in rows} == OUTFIT_PHRASES
    assert all(OUTFIT_WORDS[k][0].lower() == full.lower() for k, _, full, _ in rows)


def test_broken_path_does_not_hang() -> None:
    assert [closed for _, closed in parse_path("M0 0 L5 5 L5 0 Z 10 10")] == [True]
    assert parse_path("M0 0 S1 1 2 2") == []  # неизвестная команда — путь не читаем дальше
