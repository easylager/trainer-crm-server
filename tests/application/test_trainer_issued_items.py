"""Trainer issued passes/certificates timeline."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_issued_use_cases import list_trainer_issued_items

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _seed_trainer_client(db_session: AsyncSession) -> tuple[int, int, int]:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Ann', 'Issued', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, 'Pack 8', 8, 8000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (pass_product_id,) = r.fetchone()
    return trainer_id, client_id, pass_product_id


@pytest.mark.asyncio
async def test_list_trainer_issued_items_merges_pass_and_certificate(db_session: AsyncSession) -> None:
    trainer_id, client_id, pass_product_id = await _seed_trainer_client(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (
                client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status
            )
            VALUES (:cid, :pid, 5, 8, 8000, 'active')
            """
        ),
        {"cid": client_id, "pid": pass_product_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_certificate_products (trainer_id, name, amount_cents, is_active)
            VALUES (:tid, 'Gift 100', 10000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (cert_product_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO certificate_instances (
                trainer_id, certificate_product_id, recipient_name, amount_cents,
                amount_remaining_cents, code, status, activated_client_id
            )
            VALUES (:tid, :cpid, 'Bob Gift', 10000, 7000, 'CERT-TEST-1', 'active', :cid)
            """
        ),
        {"tid": trainer_id, "cpid": cert_product_id, "cid": client_id},
    )
    await db_session.commit()

    data = await list_trainer_issued_items(db_session, trainer_id)
    assert data["total"] == 2
    kinds = {it["kind"] for it in data["items"]}
    assert kinds == {"pass", "certificate"}

    pass_row = next(it for it in data["items"] if it["kind"] == "pass")
    assert pass_row["sessions_remaining"] == 5
    assert pass_row["sessions_total"] == 8
    assert pass_row["status_bucket"] == "active"
    assert "Ann" in pass_row["client_label_ru"]

    cert_row = next(it for it in data["items"] if it["kind"] == "certificate")
    assert cert_row["amount_remaining_cents"] == 7000
    assert cert_row["code"] == "CERT-TEST-1"
    assert cert_row["status_bucket"] == "active"

    active_only = await list_trainer_issued_items(db_session, trainer_id, status="active")
    assert active_only["total"] == 2

    passes_only = await list_trainer_issued_items(db_session, trainer_id, kind="pass")
    assert passes_only["total"] == 1
    assert passes_only["items"][0]["kind"] == "pass"

    page1 = await list_trainer_issued_items(db_session, trainer_id, limit=1, offset=0)
    assert page1["total"] == 2
    assert len(page1["items"]) == 1
    assert page1["has_more"] is True

    page2 = await list_trainer_issued_items(db_session, trainer_id, limit=1, offset=1)
    assert len(page2["items"]) == 1
    assert page2["has_more"] is False
