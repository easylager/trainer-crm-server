"""
Application layer: client ↔ trainer relationship edge use cases.

Vocabulary:
  save/unsave          — client bookmarks a trainer (UX wishlist + intent signal)
  set_primary          — client promotes a trainer to "my trainer" role
  subscribe_notify     — client subscribes to "notify when slots appear" (one-shot)
  record_booking       — called on booking create / complete to update edge counters
  notify_slot_waitlist — called from slot-creation hook; dispatches messages + clears subscriptions
  get_edges            — read all edges enriched with trainer profile data for API responses
"""
from datetime import datetime
from typing import Any

from sqlalchemy import bindparam, text

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories.client_trainer_edge_repository import ClientTrainerEdgeRepository

from src.application.demand_signals_use_cases import record_catalog_favorite


# ── write ──────────────────────────────────────────────────────────────────────

async def save_trainer(
    telegram_id: int,
    trainer_id: int,
    session: AsyncSession,
    catalog_service_id: int | None = None,
) -> tuple[dict[str, Any], bool]:
    """Bookmark trainer. Idempotent — calling twice is safe.

    Returns ``(edge, became_saved)``; ``became_saved`` is True only on the first transition to saved.
    """
    repo = ClientTrainerEdgeRepository(session)
    edge, became_saved = await repo.set_saved(
        telegram_id, trainer_id, saved=True, catalog_service_id=catalog_service_id
    )
    if became_saved:
        await record_catalog_favorite(session, trainer_id=trainer_id, source="catalog", payload=None)
    await session.commit()
    return edge, became_saved


async def unsave_trainer(
    telegram_id: int,
    trainer_id: int,
    session: AsyncSession,
) -> dict[str, Any]:
    """Remove bookmark. Idempotent."""
    repo = ClientTrainerEdgeRepository(session)
    edge, _ = await repo.set_saved(telegram_id, trainer_id, saved=False)
    await session.commit()
    return edge


async def set_primary_trainer(
    telegram_id: int,
    trainer_id: int,
    session: AsyncSession,
) -> dict[str, Any]:
    """
    Promote trainer to primary (global scope).
    Previous primary is demoted automatically; other flags stay untouched.
    Also syncs legacy selected_trainer_id for backward compat.
    """
    repo = ClientTrainerEdgeRepository(session)
    edge = await repo.set_primary(telegram_id, trainer_id)

    # Keep legacy session field in sync so old bot flows still work
    await session.execute(
        __import__("sqlalchemy").text("""
            UPDATE client_sessions
            SET selected_trainer_id = :tid_trainer, updated_at = now()
            WHERE telegram_id = :tid
        """),
        {"tid": telegram_id, "tid_trainer": trainer_id},
    )
    await session.commit()
    return edge


async def unset_primary_trainer(
    telegram_id: int,
    session: AsyncSession,
) -> None:
    """Remove primary designation entirely (no trainer is "main" now)."""
    repo = ClientTrainerEdgeRepository(session)
    await repo.unset_primary(telegram_id)
    await session.execute(
        __import__("sqlalchemy").text("""
            UPDATE client_sessions
            SET selected_trainer_id = NULL, updated_at = now()
            WHERE telegram_id = :tid
        """),
        {"tid": telegram_id},
    )
    await session.commit()


async def subscribe_notify_slots(
    telegram_id: int,
    trainer_id: int,
    session: AsyncSession,
) -> dict[str, Any]:
    """Subscribe client to one-shot slot-availability notification for a trainer."""
    repo = ClientTrainerEdgeRepository(session)
    edge = await repo.set_notify_slots(telegram_id, trainer_id, notify=True)
    await session.commit()
    return edge


async def unsubscribe_notify_slots(
    telegram_id: int,
    trainer_id: int,
    session: AsyncSession,
) -> dict[str, Any]:
    """Cancel slot-availability subscription. Idempotent."""
    repo = ClientTrainerEdgeRepository(session)
    edge = await repo.set_notify_slots(telegram_id, trainer_id, notify=False)
    await session.commit()
    return edge


async def notify_slot_waitlist(
    trainer_id: int,
    trainer_display_name: str,
    session: AsyncSession,
    send_fn,
) -> int:
    """
    Fire-and-forget: send one Telegram message per subscriber, then bulk-clear subscriptions.
    send_fn(telegram_id, text) — async callable injected by the API layer (keeps infra out of here).
    Returns count of notified clients.
    """
    repo = ClientTrainerEdgeRepository(session)
    subscribers = await repo.list_slot_subscribers(trainer_id)
    if not subscribers:
        return 0

    text_tpl = (
        "🎯 <b>Новые слоты у тренера!</b>\n\n"
        "Вы просили напомнить, когда у <b>{name}</b> появятся свободные окна.\n"
        "Слоты уже в каталоге — самое время записаться!"
    )
    msg = text_tpl.format(name=trainer_display_name)

    notified = 0
    for edge in subscribers:
        try:
            await send_fn(int(edge["telegram_id"]), msg)
            notified += 1
        except Exception:
            # Individual send failure must not abort the rest of the batch
            pass

    await repo.clear_slot_subscriptions(trainer_id)
    await session.commit()
    return notified


async def record_booking_edge(
    telegram_id: int,
    trainer_id: int,
    completed: bool = False,
    booked_at: datetime | None = None,
    session: AsyncSession | None = None,
    booking_service_id: int | None = None,
) -> None:
    """
    Update edge counters when booking is created (completed=False) or completed (completed=True).
    Caller must pass an open session; commit is the caller's responsibility
    so this can be composed in larger transactions.
    """
    if session is None:
        return
    repo = ClientTrainerEdgeRepository(session)
    await repo.record_booking(
        telegram_id,
        trainer_id,
        completed=completed,
        booked_at=booked_at,
        booking_service_id=booking_service_id,
    )


# ── read ───────────────────────────────────────────────────────────────────────

async def get_edge(
    telegram_id: int,
    trainer_id: int,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Single edge for (client, trainer); None if no relationship yet."""
    return await ClientTrainerEdgeRepository(session).get(telegram_id, trainer_id)


async def get_all_edges(
    telegram_id: int,
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """All edges for client, ordered by recency."""
    return await ClientTrainerEdgeRepository(session).list_for_client(telegram_id)


async def get_saved_edges(
    telegram_id: int,
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Only saved (bookmarked) edges, ordered by saved_at desc."""
    return await ClientTrainerEdgeRepository(session).list_saved(telegram_id)


async def get_primary_edge(
    telegram_id: int,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Primary edge for global context; None if no primary set."""
    return await ClientTrainerEdgeRepository(session).get_primary(telegram_id)


async def trainer_display_hints_by_ids(
    session: AsyncSession,
    trainer_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Catalog-style labels for trainer_id set:
      display name, list photo, services, primary arena, min price (BYN).

    Used by client "Мои тренеры" hub to power "why come back" signals — price/place/services.
    """
    uniq = sorted({int(x) for x in trainer_ids if x is not None})
    if not uniq:
        return {}
    stmt = text(
        """
        SELECT t.id AS tid,
               tp.first_name,
               tp.last_name,
               (SELECT ph.file_key FROM trainer_photos ph
                WHERE ph.trainer_id = t.id ORDER BY ph.sort_order NULLS LAST, ph.id ASC LIMIT 1) AS photo_key,
               (SELECT ph.file_key_list FROM trainer_photos ph
                WHERE ph.trainer_id = t.id ORDER BY ph.sort_order NULLS LAST, ph.id ASC LIMIT 1) AS photo_list_key,
               COALESCE(
                   (SELECT array_agg(s.name ORDER BY s.sort_order, s.id)
                    FROM trainer_services ts
                    JOIN services s ON s.id = ts.service_id
                    WHERE ts.trainer_id = t.id),
                   '{}'
               ) AS service_names,
               (SELECT a.name FROM trainer_arenas ta
                JOIN arenas a ON a.id = ta.arena_id
                WHERE ta.trainer_id = t.id AND a.is_active = true
                ORDER BY a.sort_order, a.id LIMIT 1) AS primary_arena_name,
               (SELECT MIN(pv.price_cents) FROM trainer_service_price_variants pv
                WHERE pv.trainer_id = t.id) AS min_price_cents
        FROM trainers t
        LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
        WHERE t.id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    r = await session.execute(stmt, {"ids": uniq})
    out: dict[int, dict[str, Any]] = {}
    for row in r.mappings():
        tid = int(row["tid"])
        fn = (row.get("first_name") or "").strip()
        ln = (row.get("last_name") or "").strip()
        display = (fn + " " + ln).strip() or "Тренер"
        pk = row.get("photo_key")
        pl = row.get("photo_list_key")
        raw_services = row.get("service_names") or []
        services = list(raw_services) if raw_services else []
        arena = (row.get("primary_arena_name") or "").strip() or None
        mp = row.get("min_price_cents")
        out[tid] = {
            "trainer_display_name": display,
            "trainer_list_photo_key": pl or pk,
            "services": services,
            "primary_arena_name": arena,
            "min_price_cents": int(mp) if mp is not None else None,
        }
    return out
