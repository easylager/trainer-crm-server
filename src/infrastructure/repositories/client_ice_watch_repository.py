"""Persistence for client_ice_watches."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
)


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
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        r = await self._s.execute(
            text(
                """
                INSERT INTO client_ice_watches (
                    client_id, telegram_id, arena_id, city_id, watch_kind, filter_json, active, created_at
                ) VALUES (
                    :cid, :tg, :aid, :city_id, :kind, CAST(:filter AS jsonb), true, :now
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
                    END
                RETURNING
                    id, client_id, telegram_id, arena_id, city_id, watch_kind,
                    filter_json, active, created_at, last_notified_at
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
            },
        )
        return _row_to_dict(r.fetchone())

    async def deactivate(self, client_id: int, watch_id: int) -> dict[str, Any] | None:
        r = await self._s.execute(
            text(
                """
                UPDATE client_ice_watches
                SET active = false
                WHERE id = :wid AND client_id = :cid
                RETURNING
                    id, client_id, telegram_id, arena_id, city_id, watch_kind,
                    filter_json, active, created_at, last_notified_at
                """
            ),
            {"wid": watch_id, "cid": client_id},
        )
        row = r.fetchone()
        return _row_to_dict(row) if row else None

    async def list_active_for_client(self, client_id: int) -> list[dict[str, Any]]:
        r = await self._s.execute(
            text(
                """
                SELECT
                    id, client_id, telegram_id, arena_id, city_id, watch_kind,
                    filter_json, active, created_at, last_notified_at
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
        r = await self._s.execute(
            text(
                """
                SELECT
                    id, client_id, telegram_id, arena_id, city_id, watch_kind,
                    filter_json, active, created_at, last_notified_at
                FROM client_ice_watches
                WHERE active = true AND watch_kind = :kind
                ORDER BY arena_id, id
                """
            ),
            {"kind": watch_kind},
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
                SELECT
                    id, client_id, telegram_id, arena_id, city_id, watch_kind,
                    filter_json, active, created_at, last_notified_at
                FROM client_ice_watches
                WHERE arena_id = :aid AND active = true
                {kind_sql}
                """
            ),
            params,
        )
        return [_row_to_dict(row) for row in r.fetchall()]

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
