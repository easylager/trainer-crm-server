"""Replace ice_sessions in the source horizon after an ok scrape run. Never from extractors.

TASK-187: окно — см. ``publish_horizon``. Удаляются все будущие строки парсера арены
(с сегодня, без верхней границы), вставляются только черновики внутри окна показа.
Поэтому вставка не сталкивается со старой строкой парсера (``uq_ice_sessions_parser_slot``);
``ON CONFLICT DO NOTHING`` — страховка, а не механизм.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_session_use_cases import compute_price_minor
from src.ingestion.publish_horizon import clip_to_publish_window, publish_window
from src.ingestion.scrape_runs import assert_can_replace_ice_sessions
from src.ingestion.types import CanonicalSlotDraft, PARSER_KINDS, RUN_STATUS_OK, ScrapeRunRecord

_CLIENT_KINDS = tuple(PARSER_KINDS)


class IceSessionPublisher:
    """In-memory no-op used when tests only care about extract/validate."""

    async def publish(
        self,
        run: ScrapeRunRecord,
        drafts: list[CanonicalSlotDraft],
        *,
        run_id: int | None,
    ) -> int:
        assert_can_replace_ice_sessions(run, run_id=run_id)
        return len(drafts)


class SqlAlchemyIceSessionPublisher:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(
        self,
        run: ScrapeRunRecord,
        drafts: list[CanonicalSlotDraft],
        *,
        run_id: int | None,
    ) -> int:
        assert_can_replace_ice_sessions(run, run_id=run_id)
        if run.status != RUN_STATUS_OK or not drafts:
            return 0
        window = publish_window(
            now=run.finished_at,
            timezone_name=run.publish_timezone,
            horizon_days=run.publish_horizon_days,
        )
        drafts, _beyond = clip_to_publish_window(drafts, window)
        if not drafts:
            # Нечего показать в окне — витрину не обнуляем (как пустой прогон, TASK-178).
            return 0
        # Savepoint: one bad draft (e.g. a still-oversized field) must roll back
        # only this job's DELETE+INSERTs, not the whole scheduler-tick session —
        # otherwise every other due job in the same tick loses its work too.
        async with self._session.begin_nested():
            await self._session.execute(
                text(
                    """
                    DELETE FROM ice_sessions
                    WHERE arena_id = :arena_id
                      AND kind IN ('public_skate', 'open_ice')
                      AND local_date >= :today
                      AND ends_at_utc > :now
                      AND (source_id IS NULL OR source_id NOT LIKE 'etalon_%')
                      AND (source_id IS NULL OR source_id <> 'admin')
                    """
                ),
                {
                    "arena_id": run.arena_id,
                    "today": window.today,
                    "now": window.now,
                },
            )
            for draft in drafts:
                await self._insert(draft, scrape_run_id=run_id)
        return len(drafts)

    async def _insert(self, draft: CanonicalSlotDraft, *, scrape_run_id: int | None) -> None:
        price_minor = compute_price_minor(
            draft.price_adult_minor, draft.price_child_minor, draft.price_rental_minor
        )
        source_id = draft.source_id
        if source_id is None and scrape_run_id is not None:
            source_id = f"run:{scrape_run_id}:{draft.starts_at_local}"
        await self._session.execute(
            text(
                """
                INSERT INTO ice_sessions (
                    arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                    starts_at_local, ends_at_local,
                    price_adult_minor, price_child_minor, price_rental_minor, price_minor,
                    currency_code, session_label, age_note, capacity_note, external_url, status,
                    source_id, observed_at, valid_until, schedule_basis
                ) VALUES (
                    :arena_id, :kind, :starts_at_utc, :ends_at_utc, :local_date,
                    :starts_at_local, :ends_at_local,
                    :price_adult_minor, :price_child_minor, :price_rental_minor, :price_minor,
                    :currency_code, :session_label, :age_note, :capacity_note, :external_url, :status,
                    :source_id, :observed_at, :valid_until, :schedule_basis
                )
                ON CONFLICT (arena_id, starts_at_utc, kind)
                    WHERE source_id IS NOT NULL AND source_id <> 'admin' AND source_id NOT LIKE 'etalon_%'
                DO NOTHING
                """
            ),
            {
                "arena_id": draft.arena_id,
                "kind": draft.kind,
                "starts_at_utc": draft.starts_at_utc,
                "ends_at_utc": draft.ends_at_utc,
                "local_date": draft.local_date,
                "starts_at_local": draft.starts_at_local,
                "ends_at_local": draft.ends_at_local,
                "price_adult_minor": draft.price_adult_minor,
                "price_child_minor": draft.price_child_minor,
                "price_rental_minor": draft.price_rental_minor,
                "price_minor": price_minor,
                "currency_code": draft.currency_code,
                "session_label": draft.session_label,
                "age_note": draft.age_note,
                "capacity_note": draft.capacity_note,
                "external_url": draft.external_url,
                "status": draft.status,
                "source_id": source_id,
                "observed_at": draft.observed_at,
                "valid_until": draft.valid_until,
                "schedule_basis": draft.schedule_basis,
            },
        )
