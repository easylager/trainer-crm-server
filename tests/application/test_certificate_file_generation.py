"""Background certificate PDF generation (TASK-142/AC-002).

POST /trainer/certificate-issue only inserts the row now; PDF render / S3 upload /
email are done by process_pending_certificate_files_batch, off the request path.
Covered here: a freshly issued certificate starts pending, the batch worker moves it
to ready with a real file_url, and a failed row can be requeued via retry.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.certificate_use_cases import (
    create_certificate_product,
    get_certificate_file_status,
    issue_certificate,
    process_pending_certificate_files_batch,
    retry_certificate_file_generation,
)


async def _trainer_id(db_session: AsyncSession) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_issue_certificate_starts_pending_then_batch_marks_ready(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.infrastructure.s3 as s3_module

    monkeypatch.setattr(
        s3_module,
        "upload_certificate_file",
        lambda _body, trainer_id, cert_id: f"certificates/{trainer_id}/{cert_id}.pdf",
    )

    trainer_id = await _trainer_id(db_session)
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )
    instance = await issue_certificate(
        db_session, trainer_id, product_id, recipient_name="Тест"
    )
    cert_id = instance["id"]

    status = await get_certificate_file_status(db_session, cert_id, trainer_id)
    assert status is not None
    assert status["file_status"] == "pending"
    assert status["file_url"] is None

    processed = await process_pending_certificate_files_batch(db_session, limit=10)
    assert processed >= 1

    status = await get_certificate_file_status(db_session, cert_id, trainer_id)
    assert status["file_status"] == "ready"
    assert status["file_url"]
    assert status["file_error"] is None


@pytest.mark.asyncio
async def test_process_pending_batch_marks_failed_row_without_stopping(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF-render failure lands the row in 'failed' with the error text — the batch
    itself must not raise, so one bad certificate can't stall every other trainer's
    pending row behind it."""
    import src.application.certificate_pdf as certificate_pdf_module

    def _boom(**kwargs):
        raise RuntimeError("boom: font missing")

    monkeypatch.setattr(certificate_pdf_module, "build_certificate_pdf", _boom)

    trainer_id = await _trainer_id(db_session)
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )
    instance = await issue_certificate(
        db_session, trainer_id, product_id, recipient_name="Тест"
    )
    cert_id = instance["id"]

    processed = await process_pending_certificate_files_batch(db_session, limit=10)
    assert processed >= 1

    status = await get_certificate_file_status(db_session, cert_id, trainer_id)
    assert status["file_status"] == "failed"
    assert "boom" in (status["file_error"] or "")
    assert status["file_url"] is None


@pytest.mark.asyncio
async def test_retry_certificate_file_generation_requeues_only_failed(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )
    instance = await issue_certificate(
        db_session, trainer_id, product_id, recipient_name="Тест"
    )
    cert_id = instance["id"]

    # Still pending -> retry is a no-op (nothing to retry yet).
    assert await retry_certificate_file_generation(db_session, cert_id, trainer_id) is False

    await db_session.execute(
        text(
            "UPDATE certificate_instances SET file_status = 'failed', file_error = 'boom' WHERE id = :id"
        ),
        {"id": cert_id},
    )
    await db_session.commit()

    assert await retry_certificate_file_generation(db_session, cert_id, trainer_id) is True
    status = await get_certificate_file_status(db_session, cert_id, trainer_id)
    assert status["file_status"] == "pending"
    assert status["file_error"] is None
