"""
Infrastructure: client bot session persistence. One row per telegram_id.
"""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ClientSessionRepository:
    """Client session: state, city_id, selected_trainer_id, payload. Raw SQL only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, telegram_id: int) -> dict[str, Any] | None:
        """Load session by telegram_id; None if not found."""
        r = await self._session.execute(
            text("""
                SELECT telegram_id, state, city_id, selected_service_id, selected_trainer_id, selected_arena_id, payload, updated_at
                FROM client_sessions WHERE telegram_id = :tid
            """),
            {"tid": telegram_id},
        )
        row = r.fetchone()
        if not row:
            return None
        return {
            "telegram_id": row[0],
            "state": row[1],
            "city_id": row[2],
            "selected_service_id": row[3],
            "selected_trainer_id": row[4],
            "selected_arena_id": row[5],
            "payload": row[6],
            "updated_at": str(row[7]) if row[7] else None,
        }

    async def upsert(
        self,
        telegram_id: int,
        *,
        state: str | None = None,
        city_id: int | None = None,
        selected_service_id: int | None = None,
        selected_trainer_id: int | None = None,
        selected_arena_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update session. Only non-None args are written; state default 'idle' on insert."""
        existing = await self.get(telegram_id)
        if existing:
            updates = ["updated_at = now()"]
            params: dict[str, Any] = {"tid": telegram_id}
            if state is not None: updates.append("state = :state"); params["state"] = state
            if city_id is not None: updates.append("city_id = :city_id"); params["city_id"] = city_id
            if selected_service_id is not None:
                updates.append("selected_service_id = :service_id")
                params["service_id"] = selected_service_id
            if selected_trainer_id is not None:
                updates.append("selected_trainer_id = :trainer_id")
                params["trainer_id"] = selected_trainer_id
            if selected_arena_id is not None:
                updates.append("selected_arena_id = :arena_id")
                params["arena_id"] = selected_arena_id
            if payload is not None: updates.append("payload = :payload"); params["payload"] = json.dumps(payload)
            await self._session.execute(
                text("UPDATE client_sessions SET " + ", ".join(updates) + " WHERE telegram_id = :tid"),
                params,
            )
        else:
            await self._session.execute(
                text("""
                    INSERT INTO client_sessions (telegram_id, state, city_id, selected_service_id, selected_trainer_id, selected_arena_id, payload)
                    VALUES (:tid, :state, :city_id, :service_id, :trainer_id, :arena_id, :payload)
                """),
                {
                    "tid": telegram_id,
                    "state": state or "idle",
                    "city_id": city_id,
                    "service_id": selected_service_id,
                    "trainer_id": selected_trainer_id,
                    "arena_id": selected_arena_id,
                    "payload": json.dumps(payload) if payload is not None else None,
                },
            )

    async def clear_selected_trainer(self, telegram_id: int) -> None:
        """Set selected_trainer_id = NULL (e.g. when city or service changed)."""
        await self._session.execute(
            text("""
                UPDATE client_sessions SET selected_trainer_id = NULL, updated_at = now() WHERE telegram_id = :tid
            """),
            {"tid": telegram_id},
        )

    async def clear_selected_arena(self, telegram_id: int) -> None:
        """Set selected_arena_id = NULL (e.g. when city changed)."""
        await self._session.execute(
            text("""
                UPDATE client_sessions SET selected_arena_id = NULL, updated_at = now() WHERE telegram_id = :tid
            """),
            {"tid": telegram_id},
        )

    async def clear_choices(self, telegram_id: int) -> None:
        """Set state=idle and clear city, service, arena, trainer (explicit NULL)."""
        await self._session.execute(
            text("""
                UPDATE client_sessions
                SET state = 'idle', city_id = NULL, selected_service_id = NULL, selected_trainer_id = NULL, selected_arena_id = NULL, updated_at = now()
                WHERE telegram_id = :tid
            """),
            {"tid": telegram_id},
        )
