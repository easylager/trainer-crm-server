"""Партнёры рядом с катком: реестр, блок «После катка» на сайте, чип «Кафе»."""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.application import arena_partners
from src.application.arena_partners import partners_for_arena
from src.application.place_page import _b_onsite, _b_partners

_ZAMOK = 3


def _write_registry(tmp_path, monkeypatch, partners: list[dict]) -> None:
    path = tmp_path / "arena-partners.json"
    path.write_text(json.dumps({"partners": partners}), encoding="utf-8")
    monkeypatch.setattr(arena_partners, "_REGISTRY_PATH", path)
    arena_partners._registry.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_cache():
    arena_partners._registry.cache_clear()
    yield
    arena_partners._registry.cache_clear()


def _entry(**over) -> dict:
    base = {
        "slug": "p1",
        "arena_ids": [_ZAMOK],
        "kind": "food",
        "name": "Точка",
        "offer": "−10%",
        "photos": ["partners/p1/a.jpg", "../secret.jpg"],
        "logo": "partners/p1/logo.jpg",
    }
    base.update(over)
    return base


def test_real_registry_has_mangal_house_at_zamok() -> None:
    found = partners_for_arena(_ZAMOK, today=date(2026, 10, 22))
    assert [p["slug"] for p in found] == ["mangal-house-zamok", "hinkali-spot-zamok"]
    p = found[0]
    assert p["offer"] == "−10%"
    assert p["code"] == "GLIDE"
    assert p["hours"] == "Каждый день 10:00–22:00"
    assert p["logo"] == "/static/webapp/partners/mangal-house/logo.jpg"
    assert p["phone"] is None
    h = found[1]
    assert h["offer"] == "4 хинкали за 1 коп."
    assert h["offer_note"] == "со свининой и зеленью, если заказ от 39 рублей"
    assert h["code"] == "GLIDE"
    assert h["phone"] == "+375 44 585-89-76"
    assert h["phone_tel"] == "tel:+375445858976"
    assert h["instagram"] == "https://www.instagram.com/hinkali.spot"
    assert h["instagram_handle"] == "hinkali.spot"
    assert partners_for_arena(999_999, today=date(2026, 10, 22)) == []


def test_registry_photos_from_repo_exist() -> None:
    from pathlib import Path

    root = Path(arena_partners.__file__).resolve().parents[2] / "static" / "webapp"
    found = partners_for_arena(_ZAMOK, today=date(2026, 10, 22))
    assert {p["slug"] for p in found} == {"mangal-house-zamok", "hinkali-spot-zamok"}
    for p in found:
        for url in [p["logo"], *p["photos"]]:
            assert (root / url.removeprefix("/static/webapp/")).is_file(), url


def test_partner_without_offer_is_not_shown(tmp_path, monkeypatch) -> None:
    _write_registry(tmp_path, monkeypatch, [_entry(offer="")])
    assert partners_for_arena(_ZAMOK, today=date(2026, 10, 21)) == []


def test_partner_respects_dates_and_limit(tmp_path, monkeypatch) -> None:
    _write_registry(
        tmp_path,
        monkeypatch,
        [
            _entry(slug="old", valid_to="2026-10-01"),
            _entry(slug="later", valid_from="2026-11-01"),
            *[_entry(slug=f"n{i}") for i in range(5)],
        ],
    )
    found = partners_for_arena(_ZAMOK, today=date(2026, 10, 21))
    assert [p["slug"] for p in found] == ["n0", "n1", "n2"]


def test_unsafe_asset_paths_are_dropped(tmp_path, monkeypatch) -> None:
    _write_registry(tmp_path, monkeypatch, [_entry()])
    (p,) = partners_for_arena(_ZAMOK, today=date(2026, 10, 21))
    assert p["photos"] == ["/static/webapp/partners/p1/a.jpg"]


def _card(partners: list[dict]) -> dict:
    return {
        "id": _ZAMOK,
        "city_id": 2,
        "name": "ТЦ Замок",
        "venue_type": "rink",
        "amenities": {"skate_rental": True, "cafe": True},
        "partners": partners,
    }


def test_partners_section_renders_row_and_boot_data() -> None:
    p = partners_for_arena(_ZAMOK, today=date(2026, 10, 22))
    html = _b_partners(_card(p))
    assert 'id="partners"' in html
    assert "После катка" in html
    assert "Партнёры Glide" in html
    assert html.find('data-partner="mangal-house-zamok"') < html.find(
        'data-partner="hinkali-spot-zamok"'
    )
    assert "−10% с&nbsp;Glide" in html
    assert "4 хинкали за 1 коп. с&nbsp;Glide" in html
    # Без JS строка ведёт на карту партнёра.
    assert 'href="https://yandex.ru/maps/-/CXRm54iS"' in html
    assert "/static/webapp/partner-sheet.js" in html


def test_no_partners_no_section_and_plain_cafe_chip() -> None:
    assert _b_partners(_card([])) == ""
    html = _b_onsite(_card([]), cta_url=None)
    assert 'href="#partners"' not in html
    assert "Кафе" in html


def test_cafe_chip_points_to_partners_with_offer() -> None:
    p = partners_for_arena(_ZAMOK, today=date(2026, 10, 22))
    html = _b_onsite(_card(p), cta_url=None)
    assert '<a class="b-chip" href="#partners">' in html
    assert '<span class="gp-chip-mark">−10%</span>' in html
    assert "4 хинкали" not in html


def test_instagram_query_and_bad_phone_are_dropped(tmp_path, monkeypatch) -> None:
    _write_registry(
        tmp_path,
        monkeypatch,
        [
            _entry(
                instagram="https://www.instagram.com/hinkali.spot?igsh=abc&utm_source=qr",
                phone="нет телефона",
            )
        ],
    )
    (p,) = partners_for_arena(_ZAMOK, today=date(2026, 10, 21))
    assert p["instagram"] == "https://www.instagram.com/hinkali.spot"
    assert p["instagram_handle"] == "hinkali.spot"
    assert p["phone"] is None
    assert p["phone_tel"] is None
