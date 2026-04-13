"""
PASS/CERT: trainer marks «Клиент не пришёл» without booking_problem_reports (audit in booking_client_no_show).
Does not set clients.problematic (product decision).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_problem_use_cases import classify_booking_problem_payment_class
from src.application.booking_use_cases import (
    BOOKING_STATUS_NO_SHOW,
    undo_completed_booking_pass_cert_ledger,
)
from src.shared.audit import ACTOR_API, audit_log

CHOICE_KEEP_REDEEM = "keep_redeem"
CHOICE_SKIP_REDEEM = "skip_redeem"

RESOLUTION_REDEEM = "redeem"
RESOLUTION_SKIP = "skip"

PHASE_BEFORE_COMPLETE = "before_complete"
PHASE_AFTER_REDEEM = "after_redeem"


def _instrument_ru(payment_class: str) -> str:
    return "абонемента" if payment_class == "PASS" else "сертификата"


async def get_trainer_booking_client_no_show_options(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """
    JSON for Mini App modal: phase, copy, already_recorded.
    None if booking missing / wrong trainer / slot cancelled / not PASS|CERT.
    """
    r = await session.execute(
        text(
            """
            SELECT b.id, b.client_id, b.status, s.status AS slot_status
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND b.trainer_id = :tid
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    slot_st = (row[3] or "").strip().lower()
    if slot_st == "cancelled":
        return None

    pc = await classify_booking_problem_payment_class(session, booking_id, trainer_id)
    if pc not in ("PASS", "CERT"):
        return None

    rrow = await session.execute(
        text("SELECT 1 FROM booking_client_no_show WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if rrow.fetchone():
        return {
            "payment_class": pc,
            "instrument_label": _instrument_ru(pc),
            "already_recorded": True,
            "phase": None,
            "title": "Клиент не пришёл",
            "lead": "Отметка уже сохранена.",
            "reporting_note": None,
            "primary_label": None,
            "secondary_label": None,
        }

    bstat = (row[2] or "").strip().lower()
    if bstat in ("cancelled", "declined"):
        return None

    inst = _instrument_ru(pc)

    if bstat == "completed":
        phase = PHASE_AFTER_REDEEM
        lead = f"Списание с {inst} уже прошло."
        reporting_note = "Клиента не было на занятии."
        primary_label = "Оставить списание"
        secondary_label = "Отменить списание"
    elif bstat in ("pending", "confirmed"):
        phase = PHASE_BEFORE_COMPLETE
        lead = f"Клиент не пришёл. При закрытии записи с {inst} обычно спишется занятие."
        reporting_note = "Клиента не было на занятии."
        primary_label = "Оставить списание"
        secondary_label = "Не списывать"
    else:
        # no_show / payment_dispute / completed handled; other terminal states — no new mark
        return None

    return {
        "payment_class": pc,
        "instrument_label": inst,
        "already_recorded": False,
        "phase": phase,
        "title": "Клиент не пришёл",
        "lead": lead,
        "reporting_note": reporting_note,
        "primary_label": primary_label,
        "secondary_label": secondary_label,
        "primary_choice": CHOICE_KEEP_REDEEM,
        "secondary_choice": CHOICE_SKIP_REDEEM,
    }


async def submit_trainer_booking_client_no_show(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
    choice: str,
    source: str = "mini_app",
) -> tuple[str | None, str | None]:
    """
    Returns (error_code, message) or (None, None) on success.
    error_code: not_found | bad_state | conflict | bad_request
    """
    ch = (choice or "").strip().lower()
    if ch not in (CHOICE_KEEP_REDEEM, CHOICE_SKIP_REDEEM):
        return ("bad_request", "Некорректный выбор")

    r = await session.execute(
        text(
            """
            SELECT b.id, b.client_id, b.status, s.status AS slot_status
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid AND b.trainer_id = :tid
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return ("not_found", "Запись не найдена")

    client_id = int(row[1])
    bstat = (row[2] or "").strip().lower()
    slot_st = (row[3] or "").strip().lower()
    if slot_st == "cancelled":
        return ("bad_state", "Слот отменён")
    if bstat in ("cancelled", "declined"):
        return ("bad_state", "Запись отменена или отклонена")

    rdup = await session.execute(
        text("SELECT 1 FROM booking_client_no_show WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if rdup.fetchone():
        return ("conflict", "Отметка по этой записи уже сохранена")

    legacy = await session.execute(
        text("SELECT 1 FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if legacy.fetchone():
        return ("conflict", "По этой записи уже есть отчёт — обратитесь в поддержку")

    pc = await classify_booking_problem_payment_class(session, booking_id, trainer_id)
    if pc not in ("PASS", "CERT"):
        return ("bad_request", "Действие доступно только для абонемента или сертификата")

    src = (source or "mini_app").strip()[:32] or "mini_app"

    # Phase: completed → after_redeem; pending/confirmed → before complete
    if bstat == "completed":
        if ch == CHOICE_KEEP_REDEEM:
            # No-show for analytics; ledger rows (pass_redemptions / cert credits) stay unchanged.
            await session.execute(
                text(
                    """
                    INSERT INTO booking_client_no_show (
                      booking_id, trainer_id, client_id, payment_class,
                      deduct_resolution, completed_at_submit, source
                    ) VALUES (
                      :bid, :tid, :cid, :pc, :res, true, :src
                    )
                    """
                ),
                {
                    "bid": booking_id,
                    "tid": trainer_id,
                    "cid": client_id,
                    "pc": pc,
                    "res": RESOLUTION_REDEEM,
                    "src": src,
                },
            )
            await session.execute(
                text("UPDATE bookings SET status = :st WHERE id = :bid"),
                {"st": BOOKING_STATUS_NO_SHOW, "bid": booking_id},
            )
        else:
            # CHOICE_SKIP_REDEEM: undo redemption then terminal no_show without re-redeem
            ok = await undo_completed_booking_pass_cert_ledger(session, booking_id)
            if not ok:
                return ("bad_state", "Запись не в статусе «завершено»")
            await session.execute(
                text(
                    """
                    INSERT INTO booking_client_no_show (
                      booking_id, trainer_id, client_id, payment_class,
                      deduct_resolution, completed_at_submit, source
                    ) VALUES (
                      :bid, :tid, :cid, :pc, :res, true, :src
                    )
                    """
                ),
                {
                    "bid": booking_id,
                    "tid": trainer_id,
                    "cid": client_id,
                    "pc": pc,
                    "res": RESOLUTION_SKIP,
                    "src": src,
                },
            )
            await session.execute(
                text("UPDATE bookings SET status = :st WHERE id = :bid"),
                {"st": BOOKING_STATUS_NO_SHOW, "bid": booking_id},
            )
    elif bstat in ("pending", "confirmed"):
        if ch == CHOICE_KEEP_REDEEM:
            await session.execute(
                text(
                    """
                    INSERT INTO booking_client_no_show (
                      booking_id, trainer_id, client_id, payment_class,
                      deduct_resolution, completed_at_submit, source
                    ) VALUES (
                      :bid, :tid, :cid, :pc, :res, false, :src
                    )
                    """
                ),
                {
                    "bid": booking_id,
                    "tid": trainer_id,
                    "cid": client_id,
                    "pc": pc,
                    "res": RESOLUTION_REDEEM,
                    "src": src,
                },
            )
        else:
            await session.execute(
                text(
                    """
                    INSERT INTO booking_client_no_show (
                      booking_id, trainer_id, client_id, payment_class,
                      deduct_resolution, completed_at_submit, source
                    ) VALUES (
                      :bid, :tid, :cid, :pc, :res, false, :src
                    )
                """
                ),
                {
                    "bid": booking_id,
                    "tid": trainer_id,
                    "cid": client_id,
                    "pc": pc,
                    "res": RESOLUTION_SKIP,
                    "src": src,
                },
            )
            await session.execute(
                text("UPDATE bookings SET status = :st WHERE id = :bid"),
                {"st": BOOKING_STATUS_NO_SHOW, "bid": booking_id},
            )
    else:
        return ("bad_state", "Для этого статуса действие недоступно")

    at_submit_flag = bstat == "completed"
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return ("conflict", "Отметка по этой записи уже сохранена")

    audit_log(
        "booking_client_no_show_submitted",
        ACTOR_API,
        trainer_id,
        payload={
            "booking_id": booking_id,
            "trainer_id": trainer_id,
            "client_id": client_id,
            "payment_class": pc,
            "choice": ch,
            "completed_at_submit": at_submit_flag,
            "source": src,
        },
    )
    return (None, None)
