"""TASK-028: feature-adoption idempotency (AC-004, EDGE-003)."""
from sqlalchemy import text

import pytest

from src.application.trainer_feature_tracking import (
    FEATURE_CLIENT_NOTE_WRITTEN,
    FEATURE_PASS_ISSUED,
    count_features_touched,
    record_feature_first_use,
)


async def _seed_trainer(db_session) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    tid = int(r.scalar_one())
    await db_session.commit()
    return tid


async def test_record_feature_first_use_claims_once(db_session) -> None:
    tid = await _seed_trainer(db_session)

    claimed_first = await record_feature_first_use(db_session, tid, FEATURE_PASS_ISSUED)
    await db_session.commit()
    claimed_second = await record_feature_first_use(db_session, tid, FEATURE_PASS_ISSUED)
    await db_session.commit()

    assert claimed_first is True
    assert claimed_second is False

    r = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM trainer_feature_first_use "
            "WHERE trainer_id = :tid AND feature = :f"
        ),
        {"tid": tid, "f": FEATURE_PASS_ISSUED},
    )
    assert int(r.scalar_one()) == 1


async def test_record_feature_first_use_rejects_unknown_feature(db_session) -> None:
    tid = await _seed_trainer(db_session)
    with pytest.raises(ValueError):
        await record_feature_first_use(db_session, tid, "not_a_real_feature")


async def test_count_features_touched_counts_distinct_features(db_session) -> None:
    tid = await _seed_trainer(db_session)
    await record_feature_first_use(db_session, tid, FEATURE_PASS_ISSUED)
    await record_feature_first_use(db_session, tid, FEATURE_CLIENT_NOTE_WRITTEN)
    # Repeating the same feature must not inflate the count.
    await record_feature_first_use(db_session, tid, FEATURE_PASS_ISSUED)
    await db_session.commit()

    assert await count_features_touched(db_session, tid) == 2


# ─── Integration: representative call sites (Test Strategy — a few, not all 11) ─────────


async def test_pass_issued_records_feature_first_use(db_session) -> None:
    from src.application.pass_product_use_cases import issue_pass_to_client
    from tests.db_catalog_helpers import require_seed_service_id
    from tests.conftest import belarus_test_phone, unique_test_telegram_id

    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active, sort_order)
            VALUES (:tid, 'Ab5', 5, 50000, true, 0) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (product_id,) = r.fetchone()
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            "INSERT INTO clients (telegram_id, phone, phone_normalized, first_name) "
            "VALUES (:tg, :phone, :pn, 'Pass') RETURNING id"
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.execute(
        text("INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"),
        {"tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()

    await issue_pass_to_client(db_session, trainer_id, client_id, product_id)

    assert await count_features_touched(db_session, trainer_id) == 1


async def test_client_note_written_records_feature_first_use(db_session) -> None:
    from src.application.client_notes_use_cases import upsert_trainer_client_note
    from tests.conftest import belarus_test_phone, unique_test_telegram_id

    tid = await _seed_trainer(db_session)
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            "INSERT INTO clients (telegram_id, phone, phone_normalized, first_name) "
            "VALUES (:tg, :phone, :pn, 'Noted') RETURNING id"
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()

    await upsert_trainer_client_note(db_session, tid, client_id, "  ")
    assert await count_features_touched(db_session, tid) == 0, "blank note must not claim the feature"

    await upsert_trainer_client_note(db_session, tid, client_id, "Гибкость улучшилась")
    assert await count_features_touched(db_session, tid) == 1


async def test_catalog_enabled_records_feature_first_use(db_session) -> None:
    from src.application.trainer_use_cases import set_trainer_catalog_visibility

    tid = await _seed_trainer(db_session)
    ok = await set_trainer_catalog_visibility(db_session, tid, visible=True)
    assert ok is True
    assert await count_features_touched(db_session, tid) == 1


async def test_record_feature_first_use_failure_does_not_poison_caller_transaction(
    db_session,
) -> None:
    """
    TASK-028 AC-007: a failure inside record_feature_first_use (here: FK violation from a
    trainer_id that doesn't exist — a real DB-level error, not a mock) must not raise, and
    must not leave the shared session's transaction aborted for whatever the caller does next.
    """
    nonexistent_trainer_id = 2_000_000_000

    claimed = await record_feature_first_use(
        db_session, nonexistent_trainer_id, FEATURE_PASS_ISSUED
    )
    assert claimed is False

    # The caller's own work must still go through on the same session afterwards.
    tid = await _seed_trainer(db_session)
    await db_session.commit()
    r = await db_session.execute(text("SELECT status FROM trainers WHERE id = :tid"), {"tid": tid})
    assert r.scalar_one() == "pending_profile"
