"""
Trainer-reported booking problems (PRD E2–E4): presets, audit row, client risk flag.

Payment classification: NONE | ONE_OFF | PASS | CERT (schema-driven).
Pass/cert no-show policy: P1 redeem_on_no_show | P2 skip_redeem (stored per trainer, snapshotted on report).
E4: terminal booking status (no_show / payment_dispute), optional pass/cert redemption for B1+P1, reconciliation after auto-complete.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    BOOKING_STATUS_NO_SHOW,
    BOOKING_STATUS_PAYMENT_DISPUTE,
    reverse_booking_completion_for_problem_report,
)
from src.application.certificate_use_cases import redeem_certificate_balance_for_booking
from src.application.pass_product_use_cases import redeem_pass_session_for_booking
from src.shared.audit import ACTOR_API, audit_log

# P1: auto write-off on no-show; P2: problem outcome without redemption (PRD Epic E3).
PASS_CERT_NO_SHOW_REDEEM = "redeem"
PASS_CERT_NO_SHOW_SKIP = "skip"

# Stored on booking_problem_reports.policy_breach_code when B1 + P2 (E4 T4.4); feeds client notification copy later (E5).
POLICY_BREACH_PASS_CERT_NO_SHOW_SKIP = "pass_cert_no_show_skip"

# NONE/ONE_OFF preset A1: how to reflect no-show for the client record (Mini App `client_action`).
CLIENT_ACTION_ATTENTION = "attention"
CLIENT_ACTION_BLACKLIST = "blacklist"
CLIENT_ACTION_ABSENCE_ONLY = "absence_only"


def _parse_a1_client_action(raw: str | None) -> tuple[str | None, str | None]:
    """Returns (error_message, normalized). Missing value → absence_only (default «просто отсутствие»)."""
    v = (raw or "").strip().lower()
    if not v:
        return (None, CLIENT_ACTION_ABSENCE_ONLY)
    if v in (CLIENT_ACTION_ATTENTION, CLIENT_ACTION_BLACKLIST, CLIENT_ACTION_ABSENCE_ONLY):
        return (None, v)
    return ("Некорректное значение client_action", None)


def _a1_blacklist_and_problematic(action: str) -> tuple[bool, bool]:
    """A1: (blacklist_candidate, mark_problematic)."""
    if action == CLIENT_ACTION_ABSENCE_ONLY:
        return (False, False)
    if action == CLIENT_ACTION_BLACKLIST:
        return (True, True)
    return (False, True)


# --- Presets exposed to Mini App (consequence copy is authoritative for trainer consent) ---

_PRESET_A1 = {
    "id": "A1",
    "label": "Клиент не пришёл",
    "consequences": (
        "Будет сохранён отчёт: клиент не пришёл. Эта сессия не учитывается как успешная оплата занятия для выручки. "
        "Клиент получит пометку «требует внимания» в CRM (видно вам, не блокирует запись автоматически). "
        "Автоматическая блокировка (чёрный список) не применяется."
    ),
}
_PRESET_A2 = {
    "id": "A2",
    "label": "Не оплатил",
    "consequences": (
        "Будет сохранён отчёт. Занятие не считается успешной оплатой для учёта. "
        "Клиент получит пометку «требует внимания»; отчёт может пойти на разбор администратору и в политику платформы "
        "по должникам (без автоматического списания на этом шаге)."
    ),
}
_PRESET_B2 = {
    "id": "B2",
    "label": "Проблема с оплатой (абонемент / сертификат)",
    "consequences": (
        "Будет сохранён отчёт. Клиент получит пометку «требует внимания»; сценарий может быть передан на разбор "
        "администратору (как и при спорной оплате без абонемента). Конкретное списание с абонемента или сертификата "
        "зависит от вашей политики — настройки появятся в следующей итерации."
    ),
}

_ALLOWED = {
    "NONE": ("A1", "A2"),
    "ONE_OFF": ("A1", "A2"),
    # PASS/CERT: only no-show path in product (B1); payment dispute (B2) not exposed for paid-instrument rows.
    "PASS": ("B1",),
    "CERT": ("B1",),
}
_PRESET_MAP = {"A1": _PRESET_A1, "A2": _PRESET_A2, "B2": _PRESET_B2}


def _preset_b1(pass_cert_policy: str) -> dict:
    """B1 copy depends on redeem vs skip on no-show (policy snapshot)."""
    if pass_cert_policy == PASS_CERT_NO_SHOW_SKIP:
        cons = (
            "Клиент не пришёл на занятие — это зафиксируем в отчёте.\n\n"
            "С абонемента или с сертификата занятие не спишем: так вы выбрали на прошлом шаге. "
            "При необходимости сервис может напомнить клиенту о ваших правилах."
        )
    else:
        cons = (
            "Клиент не пришёл на занятие — это зафиксируем в отчёте.\n\n"
            "После отправки занятие спишется с абонемента или с сертификата, как если клиента не было на занятии. "
            "В сводках это не будет выглядеть как «успешно оплаченное» занятие."
        )
    return {
        "id": "B1",
        "label": "Не пришёл",
        "consequences": cons,
        "pass_cert_no_show_policy": pass_cert_policy,
    }


def _normalize_explicit_pass_cert_choice(raw: str | None) -> str | None:
    """When client sends redeem|skip explicitly, use for B1 snapshot (Mini App deduct step)."""
    if not raw:
        return None
    v = str(raw).strip().lower()
    if v in (PASS_CERT_NO_SHOW_REDEEM, PASS_CERT_NO_SHOW_SKIP):
        return v
    return None


def _booking_looks_one_off(service_price_variant_id: int | None, booking_price_cents: int | None) -> bool:
    if service_price_variant_id is not None:
        return True
    return (booking_price_cents or 0) > 0


async def _load_trainer_pass_cert_no_show_policy(session: AsyncSession, trainer_id: int) -> str:
    r = await session.execute(
        text("SELECT pass_cert_no_show_policy FROM trainer_profiles WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return PASS_CERT_NO_SHOW_REDEEM
    v = str(row[0]).strip().lower()
    return v if v in (PASS_CERT_NO_SHOW_REDEEM, PASS_CERT_NO_SHOW_SKIP) else PASS_CERT_NO_SHOW_REDEEM


async def classify_booking_problem_payment_class(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> str | None:
    """
    NONE | ONE_OFF | PASS | CERT — instrument class for preset branching (PRD E3 T3.1).
    NONE: no paid instrument row and no one-off tariff snapshot on the booking.
    ONE_OFF: single-session tariff (variant / positive price cents) without pass/cert cover.
    Returns None if booking not found / wrong trainer.
    """
    r = await session.execute(
        text(
            """
            SELECT b.id, b.client_id, b.service_id, b.trainer_id, b.service_price_variant_id, b.booking_price_cents,
                   EXISTS (SELECT 1 FROM certificate_booking_credits cbc WHERE cbc.booking_id = b.id) AS has_cert_credit,
                   EXISTS (SELECT 1 FROM pass_redemptions pr WHERE pr.booking_id = b.id) AS has_pass_redemption
            FROM bookings b
            WHERE b.id = :bid AND b.trainer_id = :tid
            """
        ),
        {"bid": booking_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    client_id, service_id = int(row[1]), int(row[2])
    variant_id, price_cents = row[4], row[5]
    has_cert_credit, has_pass_redemption = bool(row[6]), bool(row[7])
    if has_cert_credit:
        return "CERT"
    if has_pass_redemption:
        return "PASS"
    r2 = await session.execute(
        text(
            """
            SELECT 1
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            WHERE pi.client_id = :cid AND p.trainer_id = :tid
              AND pi.status = 'active' AND pi.sessions_remaining > 0
              AND (p.service_id = :sid OR p.service_id IS NULL)
              AND (pi.expires_at IS NULL OR pi.expires_at > CURRENT_TIMESTAMP)
            LIMIT 1
            """
        ),
        {"cid": client_id, "tid": trainer_id, "sid": service_id},
    )
    if r2.fetchone():
        return "PASS"
    r3 = await session.execute(
        text(
            """
            SELECT 1 FROM certificate_instances ci
            WHERE ci.trainer_id = :tid
              AND (ci.client_id = :cid OR ci.activated_client_id = :cid)
              AND ci.status = 'active'
              AND COALESCE(ci.amount_remaining_cents, ci.amount_cents) > 0
              AND (ci.expires_at IS NULL OR ci.expires_at > CURRENT_TIMESTAMP)
            LIMIT 1
            """
        ),
        {"cid": client_id, "tid": trainer_id},
    )
    if r3.fetchone():
        return "CERT"
    if _booking_looks_one_off(variant_id, price_cents):
        return "ONE_OFF"
    return "NONE"


async def get_trainer_booking_problem_options(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> dict | None:
    """JSON-ready options for GET /trainer/bookings/{id}/problem-options. None if booking inaccessible."""
    exists = await session.execute(
        text("SELECT 1 FROM bookings WHERE id = :bid AND trainer_id = :tid"),
        {"bid": booking_id, "tid": trainer_id},
    )
    if not exists.fetchone():
        return None
    pc = await classify_booking_problem_payment_class(session, booking_id, trainer_id)
    if pc is None:
        return None
    rrepo = await session.execute(
        text("SELECT 1 FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    already = rrepo.fetchone() is not None
    pass_cert_policy = await _load_trainer_pass_cert_no_show_policy(session, trainer_id)
    presets_keys = _ALLOWED.get(pc, ())
    presets: list[dict] = []
    # PASS/CERT: «Клиент не пришёл» is handled by booking_client_no_show API, not problem-options presets.
    if pc in ("PASS", "CERT"):
        return {
            "payment_class": pc,
            "pass_cert_no_show_policy": pass_cert_policy,
            "already_reported": already,
            "presets": [],
            "pass_cert_no_show_flow": False,
            "pass_cert_coverage_hint": "",
            "pass_cert_pick_lead": "",
            "pass_cert_deduct_hint": "",
            "pass_cert_deduct_options": [],
            "secondary_presets": [],
        }

    if not already:
        for k in presets_keys:
            if k in _PRESET_MAP:
                presets.append({**_PRESET_MAP[k]})
    return {
        "payment_class": pc,
        "pass_cert_no_show_policy": pass_cert_policy if pc in ("PASS", "CERT") else None,
        "already_reported": already,
        "presets": presets,
        "pass_cert_no_show_flow": False,
        "pass_cert_deduct_options": [],
        "secondary_presets": [],
    }


async def submit_trainer_booking_problem(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
    preset_id: str,
    note: str | None,
    source: str,
    pass_cert_no_show_choice: str | None = None,
    client_action: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Returns (error_code, error_message) or (None, None) on success.
    error_code: not_found | bad_state | conflict | bad_preset | bad_request
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
        return ("not_found", "Запись не найдена")

    client_id = int(row[1])
    bstat = (row[2] or "").strip().lower()
    slot_st = (row[3] or "").strip().lower()
    if slot_st == "cancelled":
        return ("bad_state", "Слот отменён — отчёт недоступен")
    if bstat in ("cancelled", "declined"):
        return ("bad_state", "Запись отменена или отклонена")

    rdup = await session.execute(
        text("SELECT 1 FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if rdup.fetchone():
        return ("conflict", "По этой записи отчёт уже отправлен")

    pc = await classify_booking_problem_payment_class(session, booking_id, trainer_id)
    if pc is None:
        return ("not_found", "Запись не найдена")
    if pc in ("PASS", "CERT"):
        return (
            "bad_preset",
            "Для абонемента и сертификата используйте действие «Клиент не пришёл» в карточке записи.",
        )

    if bstat in (BOOKING_STATUS_NO_SHOW, BOOKING_STATUS_PAYMENT_DISPUTE):
        return ("bad_state", "Запись уже закрыта с отчётом о проблеме")

    if bstat == "completed":
        await reverse_booking_completion_for_problem_report(session, booking_id)

    allowed = _ALLOWED.get(pc, ())
    pid = (preset_id or "").strip()
    if pid not in allowed:
        return ("bad_preset", "Некорректный тип отчёта для этой записи")

    note_clean = (note or "").strip() or None
    if note_clean and len(note_clean) > 4000:
        return ("bad_request", "Комментарий слишком длинный")

    raw_pc_choice = (pass_cert_no_show_choice or "").strip()
    explicit_pc = _normalize_explicit_pass_cert_choice(pass_cert_no_show_choice)
    if raw_pc_choice and not explicit_pc:
        return ("bad_request", "Некорректное значение списания (redeem или skip)")
    if explicit_pc and (pid != "B1" or pc not in ("PASS", "CERT")):
        return ("bad_request", "Параметр списания не применим к этому отчёту")

    raw_ca = (client_action or "").strip()
    if raw_ca and pid != "A1":
        return ("bad_request", "Параметр client_action только для отчёта «Клиент не пришёл»")

    a1_action_saved: str | None = None
    if pid == "A1":
        err_ca, a1_action_saved = _parse_a1_client_action(client_action)
        if err_ca:
            return ("bad_request", err_ca)
        if not a1_action_saved:
            return ("bad_request", "Некорректное значение client_action")
        blacklist_candidate, mark_problematic = _a1_blacklist_and_problematic(a1_action_saved)
    elif pid == "A2":
        blacklist_candidate = True
        mark_problematic = True
    else:
        blacklist_candidate = pid in ("B2",)
        mark_problematic = True

    src = (source or "mini_app").strip()[:32] or "mini_app"
    policy_snapshot = None
    if pc in ("PASS", "CERT"):
        if pid == "B1":
            policy_snapshot = (
                explicit_pc
                if explicit_pc
                else await _load_trainer_pass_cert_no_show_policy(session, trainer_id)
            )
        else:
            policy_snapshot = await _load_trainer_pass_cert_no_show_policy(session, trainer_id)

    policy_breach_code: str | None = None
    if pid == "B1" and pc in ("PASS", "CERT") and policy_snapshot == PASS_CERT_NO_SHOW_SKIP:
        policy_breach_code = POLICY_BREACH_PASS_CERT_NO_SHOW_SKIP

    terminal_status = BOOKING_STATUS_NO_SHOW if pid in ("A1", "B1") else BOOKING_STATUS_PAYMENT_DISPUTE

    ins = await session.execute(
        text(
            """
            INSERT INTO booking_problem_reports (
              booking_id, trainer_id, client_id, preset_id, payment_class, note, source, blacklist_candidate,
              pass_cert_no_show_policy_snapshot, policy_breach_code
            ) VALUES (
              :bid, :tid, :cid, :preset, :pclass, :note, :src, :bl, :polsnap, :pbreach
            )
            RETURNING id
            """
        ),
        {
            "bid": booking_id,
            "tid": trainer_id,
            "cid": client_id,
            "preset": pid,
            "pclass": pc,
            "note": note_clean,
            "src": src,
            "bl": blacklist_candidate,
            "polsnap": policy_snapshot,
            "pbreach": policy_breach_code,
        },
    )
    report_row = ins.fetchone()
    report_id = int(report_row[0]) if report_row else 0

    await session.execute(
        text("UPDATE bookings SET status = :st WHERE id = :bid"),
        {"st": terminal_status, "bid": booking_id},
    )

    # E4 T4.3/T4.4: B1 + paid instrument — redeem only when policy P1 (snapshot redeem); P2 stores policy_breach_code only.
    if (
        pid == "B1"
        and pc in ("PASS", "CERT")
        and policy_snapshot == PASS_CERT_NO_SHOW_REDEEM
    ):
        pr_ok = await redeem_pass_session_for_booking(
            session,
            booking_id,
            allow_booking_statuses=frozenset({BOOKING_STATUS_NO_SHOW}),
        )
        if not pr_ok:
            await redeem_certificate_balance_for_booking(session, booking_id)

    if mark_problematic:
        await session.execute(
            text("UPDATE clients SET problematic = true, updated_at = now() WHERE id = :cid"),
            {"cid": client_id},
        )
    await session.commit()
    # E6 T6.1: structured compliance trail (DB row is immutable; no PII text in payload).
    audit_log(
        "booking_problem_report_submitted",
        ACTOR_API,
        trainer_id,
        payload={
            "report_id": report_id,
            "booking_id": booking_id,
            "trainer_id": trainer_id,
            "client_id": client_id,
            "preset_id": pid,
            "payment_class": pc,
            "blacklist_candidate": blacklist_candidate,
            "source": src,
            "policy_breach_code": policy_breach_code,
            "terminal_status": terminal_status,
            "has_note": bool(note_clean),
            "pass_cert_no_show_choice_explicit": bool(explicit_pc),
            "mark_problematic": mark_problematic,
            "a1_client_action": a1_action_saved if pid == "A1" else None,
        },
    )
    return (None, None)
