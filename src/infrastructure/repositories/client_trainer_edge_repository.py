"""
Infrastructure: client ↔ trainer edge-state persistence.

One row per (telegram_id, trainer_id) pair globally (nullable context_* reserved — unused).

All inserts use ON CONFLICT (telegram_id, trainer_id).
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SELECT_EDGE = """
    SELECT
        id, telegram_id, trainer_id,
        is_saved, is_primary, notify_when_slots, completed_count,
        saved_at, notify_when_slots_at,
        last_booking_at, last_completed_at, last_interaction_at,
        last_booking_service_id, saved_catalog_service_id,
        context_type, context_id, created_at
    FROM client_trainer_edges
    WHERE telegram_id = :tid AND trainer_id = :trainer_id
      AND context_type IS NOT DISTINCT FROM :ctx_type
      AND context_id   IS NOT DISTINCT FROM :ctx_id
"""

_ROW_KEYS = (
    "id", "telegram_id", "trainer_id",
    "is_saved", "is_primary", "notify_when_slots", "completed_count",
    "saved_at", "notify_when_slots_at",
    "last_booking_at", "last_completed_at", "last_interaction_at",
    "last_booking_service_id", "saved_catalog_service_id",
    "context_type", "context_id", "created_at",
)


def _row_to_dict(row) -> dict[str, Any]:
    return dict(zip(_ROW_KEYS, row))


def _merge_dup_edges(by_trainer_priority: dict[int, dict[str, Any]], row: tuple) -> None:
    """
    Postgres UNIQUE on (telegram_id, trainer_id, context_*) historically allowed duplicate
    (tid, trainer) rows when contexts were NULL. Keep the row with the largest id (newest wins).
    """
    d = _row_to_dict(row)
    tid = int(d["trainer_id"])
    cur = by_trainer_priority.get(tid)
    if cur is None or int(d["id"]) >= int(cur["id"]):
        by_trainer_priority[tid] = d


def _rows_to_list_dedupe_by_trainer(
    fetchall: list,
    sort_key=lambda d: (
        _coalesce_ts_for_sort(d.get("last_interaction_at")),
        _coalesce_ts_for_sort(d.get("saved_at")),
        _coalesce_ts_for_sort(d.get("created_at")),
    ),
) -> list[dict[str, Any]]:
    by_tid: dict[int, dict[str, Any]] = {}
    for row in fetchall:
        _merge_dup_edges(by_tid, row)
    out = list(by_tid.values())
    out.sort(key=sort_key, reverse=True)
    return out


def _coalesce_ts_for_sort(v):
    """Sort key placeholder for descending recency."""
    return v.isoformat() if hasattr(v, "isoformat") else (v if v else "")


class ClientTrainerEdgeRepository:
    """CRUD for client_trainer_edges. All methods keep context_type/context_id NULL by default (global scope)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── read ──────────────────────────────────────────────────────────────────

    async def get(
        self,
        telegram_id: int,
        trainer_id: int,
        context_type: str | None = None,
        context_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Single edge; None if not found."""
        r = await self._s.execute(
            text(_SELECT_EDGE),
            {"tid": telegram_id, "trainer_id": trainer_id, "ctx_type": context_type, "ctx_id": context_id},
        )
        row = r.fetchone()
        return _row_to_dict(row) if row else None

    async def list_for_client(self, telegram_id: int) -> list[dict[str, Any]]:
        """All edges for a client, ordered by interaction recency desc."""
        r = await self._s.execute(
            text("""
                SELECT
                    id, telegram_id, trainer_id,
                    is_saved, is_primary, notify_when_slots, completed_count,
                    saved_at, notify_when_slots_at,
                    last_booking_at, last_completed_at, last_interaction_at,
                    last_booking_service_id, saved_catalog_service_id,
                    context_type, context_id, created_at
                FROM client_trainer_edges
                WHERE telegram_id = :tid
                ORDER BY COALESCE(last_interaction_at, created_at) DESC
            """),
            {"tid": telegram_id},
        )
        rows = r.fetchall()
        return _rows_to_list_dedupe_by_trainer(rows)

    async def get_primary(
        self,
        telegram_id: int,
        context_type: str | None = None,
        context_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Return the primary edge for given context scope (NULL = global)."""
        r = await self._s.execute(
            text("""
                SELECT
                    id, telegram_id, trainer_id,
                    is_saved, is_primary, notify_when_slots, completed_count,
                    saved_at, notify_when_slots_at,
                    last_booking_at, last_completed_at, last_interaction_at,
                    last_booking_service_id, saved_catalog_service_id,
                    context_type, context_id, created_at
                FROM client_trainer_edges
                WHERE telegram_id = :tid AND is_primary = true
                  AND context_type IS NOT DISTINCT FROM :ctx_type
                  AND context_id   IS NOT DISTINCT FROM :ctx_id
                LIMIT 1
            """),
            {"tid": telegram_id, "ctx_type": context_type, "ctx_id": context_id},
        )
        row = r.fetchone()
        return _row_to_dict(row) if row else None

    async def list_saved(self, telegram_id: int) -> list[dict[str, Any]]:
        """All edges with is_saved = true, ordered by saved_at desc."""
        r = await self._s.execute(
            text("""
                SELECT
                    id, telegram_id, trainer_id,
                    is_saved, is_primary, notify_when_slots, completed_count,
                    saved_at, notify_when_slots_at,
                    last_booking_at, last_completed_at, last_interaction_at,
                    last_booking_service_id, saved_catalog_service_id,
                    context_type, context_id, created_at
                FROM client_trainer_edges
                WHERE telegram_id = :tid AND is_saved = true
                ORDER BY COALESCE(saved_at, created_at) DESC
            """),
            {"tid": telegram_id},
        )
        rows = r.fetchall()
        return _rows_to_list_dedupe_by_trainer(
            rows,
            sort_key=lambda d: (_coalesce_ts_for_sort(d.get("saved_at")), _coalesce_ts_for_sort(d.get("created_at"))),
        )

    # ── write ─────────────────────────────────────────────────────────────────

    async def ensure_edge(
        self,
        telegram_id: int,
        trainer_id: int,
        context_type: str | None = None,
        context_id: int | None = None,
    ) -> dict[str, Any]:
        """Ensure edge exists; return current state (inserted or existing)."""
        await self._s.execute(
            text("""
                INSERT INTO client_trainer_edges (telegram_id, trainer_id, context_type, context_id)
                VALUES (:tid, :trainer_id, :ctx_type, :ctx_id)
                ON CONFLICT (telegram_id, trainer_id) DO NOTHING
            """),
            {"tid": telegram_id, "trainer_id": trainer_id, "ctx_type": context_type, "ctx_id": context_id},
        )
        return await self.get(telegram_id, trainer_id, context_type, context_id)  # type: ignore[return-value]

    async def set_saved(
        self,
        telegram_id: int,
        trainer_id: int,
        saved: bool,
        context_type: str | None = None,
        context_id: int | None = None,
        *,
        catalog_service_id: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Toggle is_saved flag; sets saved_at on save, clears on unsave.

        Returns ``(edge_row, became_saved)`` where ``became_saved`` is True only when the client
        transitions to saved (was not saved before, now saved) — for one-shot trainer push.
        """
        await self.ensure_edge(telegram_id, trainer_id, context_type, context_id)
        prev = await self.get(telegram_id, trainer_id, context_type, context_id)
        was_saved = bool(prev and prev.get("is_saved"))
        now = datetime.now(timezone.utc)
        await self._s.execute(
            text("""
                UPDATE client_trainer_edges
                SET is_saved  = :saved,
                    saved_at  = CASE
                        WHEN :saved THEN CAST(:now AS TIMESTAMP WITH TIME ZONE)
                        ELSE NULL END,
                    saved_catalog_service_id = CASE
                        WHEN :saved THEN COALESCE(CAST(:svc_id AS INTEGER), saved_catalog_service_id)
                        ELSE NULL END,
                    last_interaction_at = GREATEST(last_interaction_at,
                        CAST(:now_ts AS TIMESTAMP WITH TIME ZONE))
                WHERE telegram_id = :tid AND trainer_id = :trainer_id
                  AND context_type IS NOT DISTINCT FROM :ctx_type
                  AND context_id   IS NOT DISTINCT FROM :ctx_id
            """),
            {
                "tid": telegram_id, "trainer_id": trainer_id,
                "saved": saved, "now": now, "now_ts": now,
                "svc_id": catalog_service_id,
                "ctx_type": context_type, "ctx_id": context_id,
            },
        )
        edge = await self.get(telegram_id, trainer_id, context_type, context_id)  # type: ignore[assignment]
        became_saved = bool(saved and not was_saved)
        return edge, became_saved

    async def set_primary(
        self,
        telegram_id: int,
        trainer_id: int,
        context_type: str | None = None,
        context_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Set trainer as primary for this context scope.
        Demotes previous primary (if any) — is_primary = false without touching any other flags.
        """
        await self.ensure_edge(telegram_id, trainer_id, context_type, context_id)
        await self._s.execute(
            text("""
                UPDATE client_trainer_edges
                SET is_primary = false
                WHERE telegram_id = :tid AND is_primary = true
                  AND context_type IS NOT DISTINCT FROM :ctx_type
                  AND context_id   IS NOT DISTINCT FROM :ctx_id
                  AND trainer_id   != :trainer_id
            """),
            {"tid": telegram_id, "trainer_id": trainer_id, "ctx_type": context_type, "ctx_id": context_id},
        )
        await self._s.execute(
            text("""
                UPDATE client_trainer_edges
                SET is_primary = true,
                    last_interaction_at = GREATEST(last_interaction_at, now())
                WHERE telegram_id = :tid AND trainer_id = :trainer_id
                  AND context_type IS NOT DISTINCT FROM :ctx_type
                  AND context_id   IS NOT DISTINCT FROM :ctx_id
            """),
            {"tid": telegram_id, "trainer_id": trainer_id, "ctx_type": context_type, "ctx_id": context_id},
        )
        return await self.get(telegram_id, trainer_id, context_type, context_id)  # type: ignore[return-value]

    async def unset_primary(
        self,
        telegram_id: int,
        context_type: str | None = None,
        context_id: int | None = None,
    ) -> None:
        """Clear primary flag for this context scope without removing the edge."""
        await self._s.execute(
            text("""
                UPDATE client_trainer_edges
                SET is_primary = false
                WHERE telegram_id = :tid AND is_primary = true
                  AND context_type IS NOT DISTINCT FROM :ctx_type
                  AND context_id   IS NOT DISTINCT FROM :ctx_id
            """),
            {"tid": telegram_id, "ctx_type": context_type, "ctx_id": context_id},
        )

    async def record_booking(
        self,
        telegram_id: int,
        trainer_id: int,
        completed: bool = False,
        booked_at: datetime | None = None,
        context_type: str | None = None,
        context_id: int | None = None,
        *,
        booking_service_id: int | None = None,
    ) -> None:
        """Update edge counters/timestamps when a booking is created or completed."""
        await self.ensure_edge(telegram_id, trainer_id, context_type, context_id)
        ts = booked_at or datetime.now(timezone.utc)
        await self._s.execute(
            text("""
                UPDATE client_trainer_edges
                SET
                    last_booking_at = GREATEST(last_booking_at,
                        CAST(:ts AS TIMESTAMP WITH TIME ZONE)),
                    last_interaction_at = GREATEST(last_interaction_at,
                        CAST(:ts AS TIMESTAMP WITH TIME ZONE)),
                    completed_count     = completed_count + :inc_completed,
                    last_completed_at   = CASE
                        WHEN :completed THEN GREATEST(last_completed_at,
                            CAST(:ts AS TIMESTAMP WITH TIME ZONE))
                        ELSE last_completed_at
                    END,
                    last_booking_service_id = CASE
                        WHEN :bsid IS NOT NULL THEN CAST(:bsid AS INTEGER)
                        ELSE last_booking_service_id
                    END
                WHERE telegram_id = :tid AND trainer_id = :trainer_id
                  AND context_type IS NOT DISTINCT FROM :ctx_type
                  AND context_id   IS NOT DISTINCT FROM :ctx_id
            """),
            {
                "tid": telegram_id, "trainer_id": trainer_id,
                "ts": ts, "completed": completed, "inc_completed": 1 if completed else 0,
                "bsid": booking_service_id,
                "ctx_type": context_type, "ctx_id": context_id,
            },
        )

    async def set_notify_slots(
        self,
        telegram_id: int,
        trainer_id: int,
        notify: bool,
    ) -> dict[str, Any]:
        """Subscribe/unsubscribe client from slot-availability push. One-shot by design."""
        await self.ensure_edge(telegram_id, trainer_id)
        now = datetime.now(timezone.utc)
        await self._s.execute(
            text("""
                UPDATE client_trainer_edges
                SET notify_when_slots    = :notify,
                    notify_when_slots_at = CASE
                        WHEN :notify THEN CAST(:now AS TIMESTAMP WITH TIME ZONE)
                        ELSE NULL END,
                    last_interaction_at = GREATEST(last_interaction_at,
                        CAST(:now AS TIMESTAMP WITH TIME ZONE))
                WHERE telegram_id = :tid AND trainer_id = :trainer_id
            """),
            {"tid": telegram_id, "trainer_id": trainer_id, "notify": notify, "now": now},
        )
        return await self.get(telegram_id, trainer_id)  # type: ignore[return-value]

    async def list_slot_subscribers(self, trainer_id: int) -> list[dict[str, Any]]:
        """
        All clients subscribed to slot notifications for this trainer.
        Returns lightweight dicts with just telegram_id — enough for sending messages.
        """
        r = await self._s.execute(
            text("""
                SELECT
                    id, telegram_id, trainer_id,
                    is_saved, is_primary, notify_when_slots, completed_count,
                    saved_at, notify_when_slots_at,
                    last_booking_at, last_completed_at, last_interaction_at,
                    last_booking_service_id, saved_catalog_service_id,
                    context_type, context_id, created_at
                FROM client_trainer_edges
                WHERE trainer_id = :trainer_id AND notify_when_slots = true
            """),
            {"trainer_id": trainer_id},
        )
        return [_row_to_dict(row) for row in r.fetchall()]

    async def clear_slot_subscriptions(self, trainer_id: int) -> int:
        """
        Bulk-clear notify_when_slots for all subscribers of a trainer after sending notifications.
        Returns count of cleared rows.
        """
        r = await self._s.execute(
            text("""
                UPDATE client_trainer_edges
                SET notify_when_slots    = false,
                    notify_when_slots_at = NULL
                WHERE trainer_id = :trainer_id AND notify_when_slots = true
            """),
            {"trainer_id": trainer_id},
        )
        return r.rowcount or 0
