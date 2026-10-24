import importlib.util
from pathlib import Path

from src.application.arena_visit_info import normalize_visit_info, visit_view

_DIR = Path(__file__).resolve().parents[2] / "migrations/versions"
_PATHS = ["0263_arena_profile_facts.py", "0264_grodno_rink_facts.py", "0265_molodechno_rink_facts.py", "0266_arena_facts_batch2.py", "0267_arena_facts_batch3.py"]


def _facts() -> dict:
    merged: dict = {}
    for name in _PATHS:
        spec = importlib.util.spec_from_file_location(name[:4], _DIR / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for arena_id, facts in module.FACTS.items():
            merged.setdefault(arena_id, {}).update(facts)
    return merged


def test_every_migrated_fact_passes_the_visit_info_validator_and_renders() -> None:
    for arena_id, facts in _facts().items():
        clean = normalize_visit_info({"facts": facts})
        assert set(clean["facts"]) == set(facts), arena_id
        card = {"visit_info": clean, "opening_hours": {}, "amenities": {}}
        titles = [f["key"] for f in visit_view(card)["facts"]]
        assert set(facts) <= set(titles), arena_id
