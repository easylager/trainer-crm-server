"""TASK-263: подмена битого фото на классах стиля B и один скрипт учёта звонков на страницу."""

from datetime import date
from pathlib import Path

from src.application.catalog_icons import rink_motif_svg
from src.application.city_hub_page import render_city_hub_page
from src.application.city_style_b import VARIANT_PHONE
from src.application.public_web_cta import phone_beacon_script

_B_HTML = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"
_BEACON_LISTENER = 'closest("a[data-catalog-phone-beacon]")'


def _phone_rink(arena_id: int, name: str, phone: str) -> dict:
    return {
        "id": arena_id,
        "name": name,
        "slug": f"rink-{arena_id}",
        "venue_type": "ice",
        "schedule_mode": "phone",
        "phone": phone,
        "address": "ул. Ленина, 1",
        "latitude": 52.1,
        "longitude": 26.1,
    }


def _hub_html(rinks: list[dict]) -> str:
    view = {
        "city": {"id": 7, "name": "Пинск", "country": "BY"},
        "slug": "pinsk",
        "variant": VARIANT_PHONE,
        "places": rinks,
        "nearby": [],
        "skate_counts": {},
        "today": date(2026, 10, 13),
    }
    share = {"share_url": "https://glide.example/c/pinsk", "share_text": "", "share_body": ""}
    return render_city_hub_page(
        view,
        canonical_url="https://glide.example/c/pinsk",
        og_image_url="https://glide.example/c/pinsk/og.png",
        cta_url=None,
        share=share,
        base_url="https://glide.example",
        trainers_href="",
    )


def test_phone_hub_with_two_rinks_loads_the_call_beacon_once() -> None:
    html = _hub_html(
        [
            _phone_rink(1, "Ледовая арена", "+375 165 31-00-01"),
            _phone_rink(2, "Каток Полесье", "+375 165 31-00-02"),
        ]
    )

    assert html.count("data-catalog-phone-beacon=") >= 2
    assert html.count(_BEACON_LISTENER) == 1


def test_beacon_script_only_when_the_page_has_a_call_button() -> None:
    assert phone_beacon_script('<a href="/p/x">Каток</a>') == ""
    assert _BEACON_LISTENER in phone_beacon_script('<a href="tel:+375" data-catalog-phone-beacon="/b">x</a>')


def test_broken_photo_fallback_targets_style_b_media() -> None:
    page = _B_HTML.read_text(encoding="utf-8")
    head = page.split("</head>", 1)[0]

    # Слушатель в <head>, иначе ранняя ошибка ленивой картинки проходит мимо.
    assert "addEventListener('error', dropBrokenPhoto, true)" in head
    assert "'.b-hero, .b-tile__media, .b-card2__thumb'" in head
    assert "classList.remove('b-toned-wrap')" in head
    assert ".hero__photo" not in page and ".pick__photo" not in page


def test_broken_photo_motif_matches_the_no_photo_markup() -> None:
    page = _B_HTML.read_text(encoding="utf-8")

    assert f'<template id="b-motif-hero">{rink_motif_svg(extra_class="b-hero__motif")}</template>' in page
    assert f'<template id="b-motif-small">{rink_motif_svg(small=True)}</template>' in page
