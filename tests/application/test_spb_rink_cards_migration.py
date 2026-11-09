import importlib.util
from pathlib import Path

from src.application.arena_profile import VENUE_AMENITY_KEYS
from src.application.arena_visit_info import normalize_visit_info, visit_view

_VERSIONS = Path(__file__).resolve().parents[2] / "migrations/versions"
_BATCHES = ("0311_spb_rink_cards_batch1.py", "0313_spb_rink_cards_batch2.py")


def _cards() -> dict:
    cards: dict = {}
    for name in _BATCHES:
        spec = importlib.util.spec_from_file_location(name[:-3], _VERSIONS / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert not set(cards) & set(module.CARDS), name
        cards.update(module.CARDS)
    return cards


def test_spb_cards_survive_the_visit_info_validator_and_render() -> None:
    for arena_id, card in _cards().items():
        clean = normalize_visit_info(card["visit_info"])
        assert set(clean) == set(card["visit_info"]), arena_id
        assert len(clean.get("services", [])) == len(card["visit_info"].get("services", [])), arena_id
        view = visit_view({"visit_info": clean, "opening_hours": {}, "amenities": card["amenities"]})
        assert view["facts"] or view["services"], arena_id


def test_spb_cards_use_known_amenities_and_have_a_real_description() -> None:
    for arena_id, card in _cards().items():
        assert set(card["amenities"]) <= VENUE_AMENITY_KEYS, arena_id
        assert 200 <= len(card["short_description"]) <= 400, arena_id
        assert card["website_url"].startswith("http"), arena_id
