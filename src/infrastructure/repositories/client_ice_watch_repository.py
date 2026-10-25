"""Persistence for client_ice_watches and their delivery journal."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ROW_KEYS = (
    "id",
    "client_id",
    "telegram_id",
    "arena_id",
    "city_id",
    "watch_kind",
    "filter_json",
    "active",
    "created_at",
    "last_notified_at",
    "baseline_horizon_date",
    "failed_attempts",
    "deactivated_reason",
)
_COLS = ", ".join(_ROW_KEYS)


def _row_to_dict(row) -> dict[str, Any]:
    d = dict(zip(_ROW_KEYS, row))
    fj = d.get("filter_json")
    if isinstance(fj, str):
        d["filter_json"] = json.loads(fj)
    return d


class ClientIceWatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(
        self,
        *,
        client_id: int,
        telegram_id: int,
        arena_id: int,
        watch_kind: str,
        filter_json: dict[str, Any],
        city_id: int | None,
        baseline_horizon_date: date | None = None,
    ) -> dict[str, Any]:
        """Create or reopen a watch.

        TASK-328: reopening an inactive watch takes the fresh baseline and clears the
        failure state. Re-subscribing to a still-active watch keeps its baseline: moving
        it forward could swallow sessions that appeared but were not delivered yet.
        """
        now = datetime.now(timezone.utc)
        r = await self._s.execute(
            text(
                f"""
                INSERT INTO client_ice_watches (
                    client_id, telegram_id, arena_id, city_id, watch_kind, filter_json, active, created_at,
                    baseline_horizon_date
                ) VALUES (
                    :cid, :tg, :aid, :city_id, :kind, CAST(:filter AS jsonb), true, :now, :baseline
                )
                ON CONFLICT (client_id, arena_id, watch_kind)
                DO UPDATE SET
                    filter_json = EXCLUDED.filter_json,
                    city_id = EXCLUDED.city_id,
                    telegram_id = EXCLUDED.telegram_id,
                    active = true,
                    last_notified_at = NULL,
                    created_at = CASE
                        WHEN client_ice_watches.active = false THEN EXCLUDED.created_at
                        ELSE client_ice_watches.created_at
                    END,
                    baseline_horizon_date = CASE
                        WHEN client_ice_watches.active = false THEN EXCLUDED.baseline_horizon_date
                        ELSE client_ice_watches.baseline_horizon_date
                    END,
                    failed_attempts = CASE
                        WHEN client_ice_watches.active = false THEN 0
                        ELSE client_ice_watches.failed_attempts
                    END,
                    deactivated_reason = NULL
                RETURNING {_COLS}
                """
            ),
            {
                "cid": client_id,
                "tg": telegram_id,
                "aid": arena_id,
                "city_id": city_id,
                "kind": watch_kind,
                "filter": json.dumps(filter_json or {}, ensure_ascii=False),
                "now": now,
                "baseline": baseline_horizon_date,
            },
        )
        return _row_to_dict(r.fetchone())

    async def deactivate(self, client_id: int, watch_id: int) -> dict[str, Any] | None:
        r = await self._s.execute(
            text(
                f"""
                UPDATE client_ice_watches
                SET active = false
                WHERE id = :wid AND client_id = :cid
                RETURNING {_COLS}
                """
            ),
            {"wid": watch_id, "cid": client_id},
        )
        row = r.fetchone()
        return _row_to_dict(row) if row else None

    async def list_active_for_client(self, client_id: int) -> list[dict[str, Any]]:
        r = await self._s.execute(
            text(
                f"""
                SELECT {_COLS}
                FROM client_ice_watches
                WHERE client_id = :cid AND active = true
                ORDER BY created_at DESC
                """
            ),
            {"cid": client_id},
        )
        return [_row_to_dict(row) for row in r.fetchall()]

    async def count_active_for_client(self, client_id: int) -> int:
        r = await self._s.execute(
            text(
                """
                SELECT COUNT(*)::int
                FROM client_ice_watches
                WHERE client_id = :cid AND active = true
                """
            ),
            {"cid": client_id},
        )
        return int(r.scalar() or 0)

    async def list_active_by_kind(self, watch_kind: str) -> list[dict[str, Any]]:
        return await self.list_active_by_kinds((watch_kind,))

    async def list_active_by_kinds(self, watch_kinds: tuple[str, ...]) -> list[dict[str, Any]]:
        r = await self._s.execute(
            text(
                f"""
                SELECT {_COLS}
                FROM client_ice_watches
                WHERE active = true AND watch_kind = ANY(:kinds)
                ORDER BY arena_id, id
                """
            ),
            {"kinds": list(watch_kinds)},
        )
        return [_row_to_dict(row) for row in r.fetchall()]

    async def deactivate_active_for_arena_kind(self, arena_id: int, watch_kind: str) -> int:
        r = await self._s.execute(
            text(
                """
                UPDATE client_ice_watches
                SET active = false
                WHERE arena_id = :aid AND watch_kind = :kind AND active = true
                """
            ),
            {"aid": arena_id, "kind": watch_kind},
        )
        return int(r.rowcount or 0)

    async def list_active_for_arena(self, arena_id: int, watch_kind: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"aid": arena_id}
        kind_sql = ""
        if watch_kind:
            kind_sql = " AND watch_kind = :kind"
            params["kind"] = watch_kind
        r = await self._s.execute(
            text(
                f"""
                SELECT {_COLS}
                FROM client_ice_watches
                WHERE arena_id = :aid AND active = true
                {kind_sql}
                """
            ),
            params,
        )
        return [_row_to_dict(row) for row in r.fetchall()]

    async def lock_if_active(self, watch_id: int) -> dict[str, Any] | None:
        """Row lock until commit; ``None`` if the watch was switched off meanwhile."""
        r = await self._s.execute(
            text(
                f"""
                SELECT {_COLS}
                FROM client_ice_watches
                WHERE id = :wid AND active = true
                FOR UPDATE
                """
            ),
            {"wid": watch_id},
        )
        row = r.fetchone()
        return _row_to_dict(row) if row else None

    async def mark_notified_and_deactivate(self, watch_id: int) -> None:
        now = datetime.now(timezone.utc)
        await self._s.execute(
            text(
                """
                UPDATE client_ice_watches
                SET active = false, last_notified_at = :now
                WHERE id = :wid
                """
            ),
            {"wid": watch_id, "now": now},
        )

    async def deactivate_with_reason(self, watch_id: int, reason: str) -> None:
        await self._s.execute(
            text(
                """
                UPDATE client_ice_watches
                SET active = false, deactivated_reason = :reason
                WHERE id = :wid
                """
            ),
            {"wid": watch_id, "reason": reason},
        )

    async def increment_failed_attempts(self, watch_id: int) -> int:
        r = await self._s.execute(
            text(
                """
                UPDATE client_ice_watches
                SET failed_attempts = failed_attempts + 1
                WHERE id = :wid
                RETURNING failed_attempts
                """
            ),
            {"wid": watch_id},
        )
        return int(r.scalar_one())

    async def record_delivery(
        self,
        *,
        watch_id: int,
        client_id: int,
        arena_id: int,
        attempted_at: datetime,
        ok: bool,
        error: str | None = None,
    ) -> None:
        await self._s.execute(
            text(
                """
                INSERT INTO client_ice_watch_deliveries (watch_id, client_id, arena_id, attempted_at, ok, error)
                VALUES (:wid, :cid, :aid, :at, :ok, :error)
                """
            ),
            {
                "wid": watch_id,
                "cid": client_id,
                "aid": arena_id,
                "at": attempted_at,
                "ok": ok,
                "error": (error or None) and error[:200],
            },
        )
