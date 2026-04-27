"""
Infrastructure: append-only writes + window aggregates for trainer demand signals (Lead Mode).
Raw SQL, single-purpose. Aggregation is GROUP BY over (trainer_id, kind) inside a time window —
no UPDATE on hot rows, so concurrent inserts never lock each other.
"""
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED,
    DEMAND_EVENT_CONTACT_CLICK,
    DEMAND_EVENT_KINDS,
    DEMAND_EVENT_PROFILE_VIEW,
)


class DemandSignalsRepository:
    """Append + window aggregation for trainer_demand_events. No domain logic — pure storage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_event(
        self,
        *,
        trainer_id: int,
        kind: str,
        source: str | None,
        dedup_hash: str | None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """
        Append a demand event. Returns True if inserted, False if dedup_hash collided
        with an existing row (refresh-spam suppression). Does not raise on dedup conflict.
        """
        if kind not in DEMAND_EVENT_KINDS:
            raise ValueError(f"Unknown demand event kind: {kind!r}")

        # ON CONFLICT keyed on the partial unique index ux_demand_events_dedup; the WHERE clause
        # must mirror the index predicate so Postgres can match it. Rows with dedup_hash IS NULL
        # bypass the index entirely and always insert (server-side events).
        result = await self._session.execute(
            text(
                """
                INSERT INTO trainer_demand_events (trainer_id, kind, source, dedup_hash, payload)
                VALUES (:tid, :kind, :source, :dedup, CAST(:payload AS jsonb))
                ON CONFLICT (trainer_id, kind, dedup_hash) WHERE dedup_hash IS NOT NULL DO NOTHING
                RETURNING id
                """
            ),
            {
                "tid": trainer_id,
                "kind": kind,
                "source": source,
                "dedup": dedup_hash,
                "payload": _json_dumps(payload or {}),
            },
        )
        return result.fetchone() is not None

    async def aggregate_window(
        self,
        *,
        trainer_id: int,
        kinds: Iterable[str] | None,
        since: datetime,
        until: datetime | None = None,
    ) -> dict[str, int]:
        """
        Count events per kind for one trainer in a time window. Returns dict with all
        requested kinds present (zero-filled). until=None means "now".
        """
        kinds_tuple = tuple(kinds) if kinds is not None else DEMAND_EVENT_KINDS
        if not kinds_tuple:
            return {}

        params: dict[str, Any] = {"tid": trainer_id, "since": since}
        until_clause = ""
        if until is not None:
            until_clause = " AND occurred_at < :until"
            params["until"] = until

        # Driver: do not use IN-tuple — pass each kind as a separate bind for asyncpg compatibility.
        kind_binds = [f":k{i}" for i in range(len(kinds_tuple))]
        for i, k in enumerate(kinds_tuple):
            params[f"k{i}"] = k
        kinds_in = ", ".join(kind_binds)

        result = await self._session.execute(
            text(
                f"""
                SELECT kind, COUNT(*) AS c
                FROM trainer_demand_events
                WHERE trainer_id = :tid
                  AND occurred_at >= :since{until_clause}
                  AND kind IN ({kinds_in})
                GROUP BY kind
                """
            ),
            params,
        )
        counts = {row[0]: int(row[1]) for row in result.fetchall()}
        return {kind: counts.get(kind, 0) for kind in kinds_tuple}

    async def first_event_at(
        self, *, trainer_id: int, kind: str
    ) -> datetime | None:
        """Earliest occurrence of an event kind for a trainer; None if never recorded."""
        if kind not in DEMAND_EVENT_KINDS:
            raise ValueError(f"Unknown demand event kind: {kind!r}")
        result = await self._session.execute(
            text(
                """
                SELECT MIN(occurred_at)
                FROM trainer_demand_events
                WHERE trainer_id = :tid AND kind = :kind
                """
            ),
            {"tid": trainer_id, "kind": kind},
        )
        row = result.fetchone()
        return row[0] if row and row[0] is not None else None


def _json_dumps(payload: dict[str, Any]) -> str:
    """Local helper — keeps repository decoupled from import-time json policy of use-cases."""
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "DemandSignalsRepository",
    "DEMAND_EVENT_PROFILE_VIEW",
    "DEMAND_EVENT_CONTACT_CLICK",
    "DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED",
]
