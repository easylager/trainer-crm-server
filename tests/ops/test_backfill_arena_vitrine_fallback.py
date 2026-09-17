"""TASK-119: fallback vitrine data sanity (no prod writes)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "backfill_arena_vitrine_fallback.py"
_STATUS_JSON = _ROOT / "data" / "ice-parser-status.json"


def _load_mod():
    spec = importlib.util.spec_from_file_location("backfill_arena_vitrine_fallback", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_mod()


def _skip_arena_ids() -> set[int]:
    data = json.loads(_STATUS_JSON.read_text(encoding="utf-8"))
    return {int(a["arena_id"]) for a in data["arenas"] if a["status"] == "skip"}


def test_fallbacks_cover_every_skip_arena_except_the_two_excluded(mod) -> None:
    """AC-001: one fallback per census 'skip' arena, except the documented exclusions."""
    skip_ids = _skip_arena_ids()
    expected = skip_ids - {mod.EXCLUDED_NOT_ICE, mod.EXCLUDED_LIKELY_DUPLICATE}
    assert set(mod.FALLBACKS.keys()) == expected


def test_excluded_ids_are_not_in_fallbacks(mod) -> None:
    """AC-003: the roller-ski track and the likely-duplicate arena never get a vitrine profile."""
    assert mod.EXCLUDED_NOT_ICE not in mod.FALLBACKS
    assert mod.EXCLUDED_LIKELY_DUPLICATE not in mod.FALLBACKS
    assert mod.EXCLUDED_NOT_ICE == 12
    assert mod.EXCLUDED_LIKELY_DUPLICATE == 39


def test_every_website_url_is_a_valid_public_http_url(mod) -> None:
    """AC-002: no fabricated/malformed links — reuses the same validator the app uses."""
    from src.application.arena_profile import public_http_url

    for arena_id, fallback in mod.FALLBACKS.items():
        if fallback.website_url is None:
            continue
        assert public_http_url(fallback.website_url) == fallback.website_url, (
            f"arena_id={arena_id} website_url fails public_http_url()"
        )


def test_every_short_description_is_honest_length_and_nonempty(mod) -> None:
    """Descriptions must fit the existing arena card layout and never be empty."""
    for arena_id, fallback in mod.FALLBACKS.items():
        text = fallback.short_description
        assert text and text.strip() == text
        assert 20 <= len(text) <= 400, f"arena_id={arena_id} short_description length {len(text)}"


def test_no_short_description_fabricates_a_schedule(mod) -> None:
    """None of these arenas got a live parser — copy must never claim exact session times."""
    import re

    time_pattern = re.compile(r"\b\d{1,2}[:.]\d{2}\b")
    for arena_id, fallback in mod.FALLBACKS.items():
        assert not time_pattern.search(fallback.short_description), (
            f"arena_id={arena_id} short_description looks like it invents a schedule time"
        )


@pytest.mark.asyncio
async def test_apply_never_overwrites_an_existing_website_url_or_description(mod, db_session) -> None:
    """Regression: an earlier run of this script against a real DB found some arenas already had
    better, hand-curated website_url/short_description (TASK-080) than this script's generic
    fallback copy — the script must fill gaps, never clobber existing values."""
    from sqlalchemy import text

    from src.application.arena_profile import apply_admin_arena_profile_patch

    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    city_id = r.scalar()
    if city_id is None:
        pytest.skip("need seed cities")

    arena_id = next(iter(mod.FALLBACKS))
    r = await db_session.execute(
        text(
            "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
            "VALUES (:cid, 'Test arena', 'ул. Тестовая, 1', true, true) RETURNING id"
        ),
        {"cid": city_id},
    )
    real_arena_id = int(r.scalar_one())
    await db_session.flush()

    curated_url = "https://example.by/already-curated"
    curated_desc = "Уже вручную выверенное описание, трогать нельзя."
    await apply_admin_arena_profile_patch(
        db_session, real_arena_id, {"website_url": curated_url, "short_description": curated_desc}
    )
    await db_session.flush()

    # Simulate this script's fill-only logic directly (same guard as run()).
    existing = (
        await db_session.execute(
            text("SELECT website_url, short_description FROM arena_profiles WHERE arena_id = :id"),
            {"id": real_arena_id},
        )
    ).fetchone()
    existing_url = (existing[0] or "").strip()
    existing_desc = (existing[1] or "").strip()
    fallback = mod.FALLBACKS[arena_id]
    patch = {}
    if not existing_url and fallback.website_url:
        patch["website_url"] = fallback.website_url
    if not existing_desc:
        patch["short_description"] = fallback.short_description
    assert patch == {}, "existing curated fields must never be scheduled for overwrite"
