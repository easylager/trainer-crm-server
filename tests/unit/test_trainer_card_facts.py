"""TASK-399: плашка фактов — одна таблица с JS, флаг выключен не меняет старые строки."""

from __future__ import annotations

import json
from pathlib import Path

from src.application.site_trainer_page import _audience, _hero
from src.application.trainer_card_facts import fact_strip
from src.shared.config import Settings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "trainer_card_facts.json"
# Снято с _hero до правки TASK-399, флаг выключен: «Дети и взрослые.» на месте.
_HERO_BEFORE = (
    '<section class="tp-th"><div class="tp-top">'
    '<span class="tp-ava tp-ava--mono" aria-hidden="true">А</span>'
    '<div class="tp-head"><span class="tp-badge">Тренирует 7 лет</span>'
    '<h1 class="tp-name">Анна<span class="tp-trade"> — тренер по катанию на коньках в Минске</span></h1>'
    '<p class="tp-role">Занятия с нуля. Дети и взрослые.</p></div></div><card/></section>'
)


def _cases() -> list[dict]:
    return list(json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"])


def _svc(*kinds: str) -> dict:
    return {"price_tiers": [{"tier_kind": k, "price_cents": 5000} for k in kinds]}


def test_flag_defaults_off() -> None:
    assert Settings.model_fields["unified_trainer_card_enabled"].default is False


def test_fact_strip_matches_shared_fixture() -> None:
    for case in _cases():
        assert fact_strip(case) == case["facts"], case["id"]


def test_raw_service_audience_matches_shared_fixture(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))["raw_services"]
    for case in raw:
        assert _audience(case["services"]) == case["audience"], case["id"]


def test_fact_strip_has_no_lesson_count_or_rating() -> None:
    facts = [item for case in _cases() for item in fact_strip(case)]
    labels = {item["label"] for item in facts}
    assert labels <= {"тренерского опыта", "учеников", "основной каток", "за занятие"}
    blob = " ".join(item["value"] for item in facts)
    assert "★" not in blob
    assert "оцен" not in blob
    assert "раз" not in blob


def test_audience_flag_off_matches_hero_snapshot(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "false")
    assert _audience([_svc("child", "adult")]) == "Дети и взрослые."
    assert _audience([_svc("child")]) == "Дети."
    assert _audience([_svc("two_children")]) == "Дети."
    assert _audience([_svc("adult")]) == ""
    assert _audience([_svc("adult_and_child")]) == "Дети и взрослые."
    assert _audience([_svc()]) == ""
    assert _audience([]) == ""
    page = {
        "name": "Анна",
        "initial": "А",
        "photo_url": None,
        "experience_years": 7,
        "city_name": "Минск",
        "directions": [{"key": "zero"}],
        "audience": _audience([_svc("child", "adult")]),
        "description": "",
        "rating_avg": None,
        "rating_count": 0,
        "education": None,
        "arenas": [],
        "glide_since": None,
    }
    assert _hero(page, "<card/>", compact=False) == _HERO_BEFORE


def test_audience_flag_on_matches_strip_labels(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    assert _audience([_svc("child")]) == "Дети"
    assert _audience([_svc("two_children")]) == "Дети"
    assert _audience([_svc("adult")]) == "Любой возраст"
    assert _audience([_svc("child", "adult")]) == "Любой возраст"
    assert _audience([_svc("adult_and_child")]) == "Любой возраст"
    assert _audience([]) == "Любой возраст"


def test_trainers_html_unchanged_when_flag_off(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "false")
    from src.api.app import webapp_trainers_page
    from src.api.asset_stamp import stamp_html

    path = Path(__file__).resolve().parents[2] / "static" / "webapp" / "trainers.html"
    body = webapp_trainers_page().body.decode()
    assert body == stamp_html(path.read_text(encoding="utf-8"))
    assert "__UNIFIED_TRAINER_CARD__" not in body


def test_trainers_html_carries_flag_when_on(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    from src.api.app import _UNIFIED_TRAINER_CARD_BOOT, webapp_trainers_page
    from src.api.asset_stamp import stamp_html

    path = Path(__file__).resolve().parents[2] / "static" / "webapp" / "trainers.html"
    stamped = stamp_html(path.read_text(encoding="utf-8"))
    body = webapp_trainers_page().body.decode()
    assert body == stamped.replace("</head>", _UNIFIED_TRAINER_CARD_BOOT + "</head>", 1)
    assert body.count("__UNIFIED_TRAINER_CARD__") == 1
