"""
Group cohort RSVP: Telegram prompts before a slot; «Буду» creates a confirmed booking (same occupancy rules).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    create_booking,
    generate_reminders_for_booking,
    is_slot_end_in_past_local,
)
from src.application.training_group_use_cases import MEMBER_ACTIVE, MEMBER_TRIAL
from src.shared.notification_hours import NOTIFICATION_TZ
import src.infrastructure.db as db_module

logger = logging.getLogger(__name__)

GAP_PENDING = "pending"
GAP_SENT = "sent"
GAP_SKIPPED = "skipped"
GAP_FAILED = "failed"
GAP_CANCELLED = "cancelled"

RESP_YES = "yes"
RESP_NO = "no"


def _rsvp_secret_from_bot_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def rsvp_hmac_secret(bot_token: str) -> str:
    """HMAC key derived from client bot token (stable, not sent to Telegram)."""
    return _rsvp_secret_from_bot_token(bot_token)


def attendance_rsvp_sign(prompt_id: int, action: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{prompt_id}:{action}".encode(), hashlib.sha256).hexdigest()[:10]


def attendance_rsvp_verify(prompt_id: int, action: str, sig: str, secret: str) -> bool:
    try:
        return hmac.compare_digest(attendance_rsvp_sign(prompt_id, action, secret), sig)
    except Exception:
        return False


def slot_send_at_utc(slot_date: date, start_time: time, hours_before: int) -> datetime:
    """When to send RSVP prompt: slot start in NOTIFICATION_TZ minus hours_before → UTC."""
    local_tz = ZoneInfo(NOTIFICATION_TZ)
    slot_local = datetime.combine(slot_date, start_time, tzinfo=local_tz)
    send_local = slot_local - timedelta(hours=max(1, int(hours_before)))
    return send_local.astimezone(timezone.utc)


async def _cleanup_prompt_states(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            UPDATE group_attendance_prompts p
            SET status = :st
            FROM slots s
            WHERE p.slot_id = s.id AND s.status = 'cancelled'
              AND p.status IN ('pending', 'sent')
              AND p.response IS NULL
            """
        ),
        {"st": GAP_CANCELLED},
    )
    await session.execute(
        text(
            """
            UPDATE group_attendance_prompts p
            SET status = :st
            WHERE p.status = 'pending'
              AND NOT EXISTS (
                SELECT 1 FROM training_group_members m
                WHERE m.training_group_id = p.training_group_id
                  AND m.client_id = p.client_id
                  AND m.status IN (:a, :t)
              )
            """
        ),
        {"st": GAP_SKIPPED, "a": MEMBER_ACTIVE, "t": MEMBER_TRIAL},
    )


async def sync_group_attendance_prompts(session: AsyncSession, hours_before: int) -> int:
    """
    Ensure prompt rows exist for future group slots × roster members without a booking.
    Returns approximate number of INSERT attempts (best-effort).
    """
    await _cleanup_prompt_states(session)
    now_utc = datetime.now(timezone.utc)
    r = await session.execute(
        text(
            """
            SELECT s.id, s.slot_date, s.start_time, s.training_group_id
            FROM slots s
            WHERE s.training_group_id IS NOT NULL
              AND s.status != 'cancelled'
              AND (
                s.slot_date > CURRENT_DATE
                OR (s.slot_date = CURRENT_DATE AND s.start_time > CURRENT_TIME)
              )
              AND s.slot_date <= CURRENT_DATE + interval '56 days'
            """
        ),
    )
    rows = r.fetchall()
    hb = max(1, int(hours_before))
    for row in rows:
        sid = int(row[0])
        sd: date = row[1]
        st: time = row[2]
        gid = int(row[3])
        send_at = slot_send_at_utc(sd, st, hb)
        if send_at < now_utc:
            send_at = now_utc
        r_m = await session.execute(
            text(
                """
                SELECT m.client_id
                FROM training_group_members m
                WHERE m.training_group_id = :gid AND m.status IN (:a, :t)
                  AND NOT EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.slot_id = :sid AND b.client_id = m.client_id
                      AND b.status IN ('pending', 'confirmed')
                  )
                """
            ),
            {"gid": gid, "sid": sid, "a": MEMBER_ACTIVE, "t": MEMBER_TRIAL},
        )
        for (cid,) in r_m.fetchall():
            cid = int(cid)
            await session.execute(
                text(
                    """
                    INSERT INTO group_attendance_prompts (
                        slot_id, client_id, training_group_id, send_at, status
                    )
                    VALUES (:sid, :cid, :gid, :sat, 'pending')
                    ON CONFLICT (slot_id, client_id) DO NOTHING
                    """
                ),
                {"sid": sid, "cid": cid, "gid": gid, "sat": send_at},
            )
    await session.commit()
    return len(rows)


async def list_pending_attendance_prompts(session: AsyncSession, limit: int = 50) -> list[dict]:
    r = await session.execute(
        text(
            """
            SELECT p.id, p.slot_id, p.client_id, p.training_group_id,
                   c.telegram_id,
                   s.slot_date, s.start_time, s.end_time,
                   tg.name AS group_name
            FROM group_attendance_prompts p
            JOIN clients c ON c.id = p.client_id
            JOIN slots s ON s.id = p.slot_id
            JOIN training_groups tg ON tg.id = p.training_group_id
            WHERE p.status = 'pending'
              AND p.send_at <= NOW()
              AND s.status != 'cancelled'
              AND c.telegram_id IS NOT NULL
            ORDER BY p.send_at
            LIMIT :lim
            FOR UPDATE OF p SKIP LOCKED
            """
        ),
        {"lim": max(1, min(limit, 200))},
    )
    out: list[dict] = []
    for row in r.fetchall():
        out.append(
            {
                "id": int(row[0]),
                "slot_id": int(row[1]),
                "client_id": int(row[2]),
                "training_group_id": int(row[3]),
                "client_telegram_id": int(row[4]),
                "slot_date": row[5],
                "start_time": row[6],
                "end_time": row[7],
                "group_name": (row[8] or "").strip() or "Группа",
            }
        )
    return out


async def mark_attendance_prompt_sent(session: AsyncSession, prompt_id: int) -> None:
    await session.execute(
        text(
            """
            UPDATE group_attendance_prompts
            SET status = :st, sent_at = NOW()
            WHERE id = :id AND status = 'pending'
            """
        ),
        {"id": prompt_id, "st": GAP_SENT},
    )
    await session.commit()


async def mark_attendance_prompt_failed(session: AsyncSession, prompt_id: int, err: str) -> None:
    await session.execute(
        text(
            """
            UPDATE group_attendance_prompts
            SET status = :st, error = :err
            WHERE id = :id AND status = 'pending'
            """
        ),
        {"id": prompt_id, "st": GAP_FAILED, "err": (err or "")[:2000]},
    )
    await session.commit()


async def skip_attendance_prompts_for_removed_member(
    session: AsyncSession, training_group_id: int, client_id: int, *, do_commit: bool = True
) -> None:
    await session.execute(
        text(
            """
            UPDATE group_attendance_prompts p
            SET status = :st
            FROM slots s
            WHERE p.slot_id = s.id
              AND p.training_group_id = :gid AND p.client_id = :cid
              AND p.status = 'pending'
              AND p.response IS NULL
              AND s.status != 'cancelled'
              AND (
                s.slot_date > CURRENT_DATE
                OR (s.slot_date = CURRENT_DATE AND s.start_time > CURRENT_TIME)
              )
            """
        ),
        {"st": GAP_SKIPPED, "gid": training_group_id, "cid": client_id},
    )
    if do_commit:
        await session.commit()


async def respond_attendance_rsvp(
    *,
    prompt_id: int,
    telegram_user_id: int,
    accept: bool,
) -> tuple[bool, str]:
    """
    Process RSVP callback. Returns (ok, user_message).
    """
    async with db_module.async_session_factory() as session:
        r = await session.execute(
            text(
                """
                SELECT p.id, p.slot_id, p.client_id, p.training_group_id, p.status, p.response,
                       c.telegram_id, s.trainer_id, s.service_id, s.capacity, s.status AS slot_status,
                       s.slot_date, s.start_time, s.end_time
                FROM group_attendance_prompts p
                JOIN clients c ON c.id = p.client_id
                JOIN slots s ON s.id = p.slot_id
                WHERE p.id = :pid
                """
            ),
            {"pid": prompt_id},
        )
        row = r.fetchone()
    if not row:
        return False, "Запрос не найден."
    st = (row[4] or "").strip()
    existing_resp = row[5]
    client_tid = row[6]
    if client_tid is None or int(client_tid) != int(telegram_user_id):
        return False, "Это не ваш запрос."

    if existing_resp in (RESP_YES, RESP_NO):
        if existing_resp == RESP_YES:
            return True, "Вы уже подтвердили участие."
        return True, "Вы уже ответили, что не сможете прийти."

    if st == GAP_CANCELLED or st == GAP_SKIPPED:
        return False, "Это занятие больше не актуально."
    if st not in (GAP_SENT, GAP_PENDING):
        return False, "Запрос уже обработан."

    slot_status = (row[10] or "").strip().lower()
    if slot_status == "cancelled":
        return False, "Занятие отменено."

    slot_date: date = row[11]
    end_t: time = row[13]
    if is_slot_end_in_past_local(slot_date, end_t):
        return False, "Занятие уже прошло."

    if not accept:
        async with db_module.async_session_factory() as s1:
            await s1.execute(
                text(
                    """
                    UPDATE group_attendance_prompts
                    SET response = :r, responded_at = NOW()
                    WHERE id = :id AND response IS NULL
                    """
                ),
                {"id": prompt_id, "r": RESP_NO},
            )
            await s1.commit()
        return True, "Принято. Ждём вас на следующих занятиях!"

    slot_id = int(row[1])
    client_id = int(row[2])
    trainer_id = int(row[7])
    service_id = row[8]
    if service_id is None:
        return False, "Ошибка конфигурации слота."
    service_id = int(service_id)

    async with db_module.async_session_factory() as s0:
        r_mem = await s0.execute(
            text(
                """
                SELECT 1 FROM training_group_members
                WHERE training_group_id = :gid AND client_id = :cid AND status IN (:a, :t)
                """
            ),
            {"gid": int(row[3]), "cid": client_id, "a": MEMBER_ACTIVE, "t": MEMBER_TRIAL},
        )
        if not r_mem.fetchone():
            return False, "Вы не в составе этой группы."

        r_existing = await s0.execute(
            text(
                """
                SELECT id FROM bookings
                WHERE slot_id = :sid AND client_id = :cid AND status IN ('pending', 'confirmed')
                LIMIT 1
                """
            ),
            {"sid": slot_id, "cid": client_id},
        )
        if r_existing.fetchone():
            await s0.execute(
                text(
                    """
                    UPDATE group_attendance_prompts
                    SET response = :r, responded_at = NOW()
                    WHERE id = :id AND response IS NULL
                    """
                ),
                {"id": prompt_id, "r": RESP_YES},
            )
            await s0.commit()
            return True, "Вы уже записаны на это занятие."

    async with db_module.async_session_factory() as s_book:
        bid, _ = await create_booking(
            s_book,
            slot_id,
            trainer_id,
            client_id,
            service_id,
            client_comment="group_rsvp",
            created_by_trainer=True,
        )
    if bid is None:
        return False, "Не удалось записаться: возможно, не осталось мест."

    async with db_module.async_session_factory() as s2:
        await s2.execute(
            text(
                """
                UPDATE group_attendance_prompts
                SET response = :r, responded_at = NOW(), booking_id = :bid
                WHERE id = :id
                """
            ),
            {"r": RESP_YES, "bid": bid, "id": prompt_id},
        )
        await s2.commit()

    async with db_module.async_session_factory() as s3:
        try:
            await generate_reminders_for_booking(s3, bid)
        except Exception as e:
            logger.warning("generate_reminders_for_booking after RSVP: %s", e)

    return True, "Запись подтверждена. До встречи на занятии!"
