"""TASK-063: dossier parser + local loader (no prod writes)."""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "load_minsk_arena_cards.py"
_CARDS = _ROOT / ".ai" / "data" / "arena-cards"

EXPECTED_IDS = {
    "minskarena": 2,
    "zamok": 3,
    "ledlife": 4,
    "minsk-ledlife": 4,
    "ledby": 5,
    "chizhovka": 6,
    "minsk-diamond": 7,
    "minsk-junost": 8,
}


def _load_mod():
    spec = importlib.util.spec_from_file_location("load_minsk_arena_cards", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def loader():
    return _load_mod()


@pytest.fixture(scope="module")
def cards(loader):
    paths = loader.discover_dossiers(_CARDS)
    parsed = [loader.parse_dossier(path) for path in paths]
    return {card.slug: card for card in parsed}


def test_dry_run_parses_all_seven_dossiers(cards) -> None:
    assert len(cards) == 7
    by_id = {card.arena_id: card.slug for card in cards.values()}
    assert by_id[2] == "minskarena"
    assert by_id[3] == "zamok"
    assert by_id[6] == "chizhovka"
    assert by_id[5] == "ledby"
    assert by_id[7] == "minsk-diamond"
    assert by_id[8] == "minsk-junost"
    assert by_id[4] == "minsk-ledlife"
    for card in cards.values():
        assert card.arena_id in EXPECTED_IDS.values()
        assert card.enough_facts
        assert card.status == "published"
        assert all(p.action == "skip" for p in card.photo_decisions)


def test_zamok_is_the_fullest_card(cards) -> None:
    zamok = cards["zamok"]
    assert zamok.district == "Центральный район"
    assert zamok.phone and zamok.phone.startswith("+375")
    assert len(zamok.phone) <= 32
    assert zamok.website_url == "https://tczamok.by/entertainments/ice-rink"
    assert zamok.opening_hours is not None
    assert zamok.opening_hours["daily"] == {"open": "10:00", "close": "23:00"}
    assert zamok.season_start_month == 1
    assert zamok.season_end_month == 12
    assert zamok.amenities == {
        "skate_rental": True,
        "skate_sharpening": True,
        "locker_rooms": True,
        "cafe": True,
    }
    assert "parking" not in zamok.amenities
    assert "accessibility" not in zamok.amenities
    assert zamok.social_urls["vk"].startswith("https://vk.com/")
    assert zamok.social_urls["instagram"]
    assert zamok.short_description
    assert all(p.action == "skip" for p in zamok.photo_decisions)
    assert any("нужно разрешение" in p.reason for p in zamok.photo_decisions)


def test_unknown_amenities_stay_unset(cards) -> None:
    assert cards["minskarena"].amenities == {}
    assert cards["minsk-ledlife"].amenities == {}
    assert cards["minsk-ledlife"].phone is None
    assert cards["minsk-ledlife"].opening_hours is None
    assert cards["minsk-junost"].opening_hours is None
    assert cards["minskarena"].season_start_month is None
    assert cards["minskarena"].season_end_month is None
    diamond = cards["minsk-diamond"]
    assert diamond.amenities == {"skate_rental": True, "locker_rooms": True}
    assert "parking" not in diamond.amenities
    assert diamond.social_urls == {}


def test_photo_decisions_skip_cdn_and_diamond_wait_grant(cards) -> None:
    diamond = cards["minsk-diamond"]
    reasons = " ".join(p.reason for p in diamond.photo_decisions)
    assert "wait for grant" in reasons
    assert diamond.publishable_photo_count == 0
    junost = cards["minsk-junost"]
    assert any("403" in p.reason or "нужно разрешение" in p.reason for p in junost.photo_decisions)
    assert "junost.by origin 403" in junost.blockers[0]
    assert "ledlife.by origin 403" in cards["minsk-ledlife"].blockers[0]


def test_compact_phone_fits_column(loader) -> None:
    two = loader.compact_phone("+375 (44) 783-85-18; +375 (17) 309-54-76")
    assert two is not None and len(two) <= 32
    three = loader.compact_phone(
        "администратор +375 29 323-22-09 (A1); городской +375 17 397-88-37; автоинформатор +375 17 348-26-87"
    )
    assert three == "+375293232209"
    assert loader.compact_phone("unknown") is None


def test_session_plan_skips_empty_and_403(loader, tmp_path: Path) -> None:
    card = loader.parse_dossier(_CARDS / "minsk-junost.md")
    empty_dir = tmp_path / "minsk-junost"
    empty_dir.mkdir()
    (empty_dir / "expected.json").write_text(
        json.dumps({"blocked_without_by_egress": True, "http_status": 403, "sessions": []}),
        encoding="utf-8",
    )
    plan = loader.plan_sessions(card, tmp_path)
    assert plan.seed is False
    assert "403" in plan.reason

    missing = loader.plan_sessions(loader.parse_dossier(_CARDS / "minsk-zamok.md"), tmp_path)
    assert missing.seed is False
    assert "no expected.json" in missing.reason


def test_session_plan_clips_to_seven_days(loader, tmp_path: Path) -> None:
    card = loader.parse_dossier(_CARDS / "minsk-zamok.md")
    fixture_dir = tmp_path / "minsk-zamok"
    fixture_dir.mkdir()
    start = date(2026, 9, 1)
    sessions = []
    for offset in range(8):
        day = start + timedelta(days=offset)
        sessions.append(
            {
                "kind": "public_skate",
                "local_date": day.isoformat(),
                "starts_at_local": "10:00",
                "ends_at_local": "10:45",
                "price_adult_minor": 1100,
                "price_child_minor": 900,
                "currency_code": "BYN",
            }
        )
    sessions.append(
        {
            "kind": "rental",
            "local_date": "2026-09-01",
            "starts_at_local": "11:00",
            "ends_at_local": "12:00",
            "currency_code": "BYN",
        }
    )
    (fixture_dir / "expected.json").write_text(json.dumps({"sessions": sessions}), encoding="utf-8")
    plan = loader.plan_sessions(card, tmp_path)
    assert plan.seed is True
    assert len(plan.rows) == 7
    assert plan.clipped == 1
    assert plan.skipped_kind == 1
    assert plan.horizon_end == date(2026, 9, 7)
    assert plan.valid_until is not None
    assert plan.valid_until.date() == date(2026, 9, 7)


def test_refuses_production_database_url(loader) -> None:
    with pytest.raises(loader.ProdDatabaseError):
        loader.assert_local_database_url(
            "postgresql://u:p@prod.railway.app:5432/trainer_crm", apply=True
        )
    with pytest.raises(loader.ProdDatabaseError):
        loader.assert_local_database_url(
            "postgresql://u:p@db.example.com:5432/trainer_crm_test", apply=True
        )
    loader.assert_local_database_url(
        "postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm_test",
        apply=True,
    )
    with pytest.raises(loader.ProdDatabaseError):
        loader.assert_local_database_url(
            "postgresql://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm",
            apply=True,
        )
    loader.assert_local_database_url(
        "postgresql://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm",
        apply=True,
        allow_local_dev=True,
    )


@pytest.mark.asyncio
async def test_apply_updates_zamok_profile_unknown_amenities_unset(
    loader, cards, db_session, tmp_path: Path
) -> None:
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")
    name = f"Замок-loader-{uuid.uuid4().hex[:8]}"
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'пр-т Победителей 65', true, true)
            RETURNING id
            """
        ),
        {"cid": int(city), "name": name},
    )
    arena_id = int(ins.scalar_one())
    await db_session.flush()

    fixture_dir = tmp_path / "minsk-zamok"
    fixture_dir.mkdir()
    (fixture_dir / "expected.json").write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "kind": "public_skate",
                        "local_date": "2026-09-06",
                        "starts_at_local": "10:15",
                        "ends_at_local": "11:00",
                        "price_adult_minor": 1100,
                        "price_child_minor": 900,
                        "price_rental_minor": 900,
                        "currency_code": "BYN",
                        "age_note": "детский от 3 до 14 лет",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = await loader.apply_card(
        db_session,
        cards["zamok"],
        fixtures_dir=tmp_path,
        seed_sessions=True,
        arena_id=arena_id,
    )
    await db_session.flush()
    assert result.error is None
    assert result.sessions_seeded == 1

    row = (
        await db_session.execute(
            text(
                """
                SELECT district, phone, website_url, opening_hours, season_start_month,
                       season_end_month, amenities, short_description, social_urls, status
                FROM arena_profiles WHERE arena_id = :id
                """
            ),
            {"id": arena_id},
        )
    ).fetchone()
    assert row is not None
    assert row[0] == "Центральный район"
    assert row[1] and str(row[1]).startswith("+375")
    assert "tczamok.by" in (row[2] or "")
    assert row[3]["daily"]["open"] == "10:00"
    assert row[4] == 1 and row[5] == 12
    amenities = row[6]
    assert amenities["skate_rental"] is True
    assert amenities["cafe"] is True
    assert "parking" not in amenities
    assert "accessibility" not in amenities
    assert row[7]
    assert row[8].get("vk")
    assert row[9] == "published"

    media_count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM media WHERE owner_type = 'arena' AND owner_id = :id"),
            {"id": arena_id},
        )
    ).scalar()
    assert int(media_count or 0) == 0

    seeded = (
        await db_session.execute(
            text(
                """
                SELECT source_id, kind, valid_until FROM ice_sessions
                WHERE arena_id = :id AND source_id = :src
                """
            ),
            {"id": arena_id, "src": loader.SOURCE_ETALON},
        )
    ).fetchone()
    assert seeded is not None
    assert seeded[0] == "etalon_073"
    assert seeded[1] == "public_skate"
    assert seeded[2] is not None
