"""Replace ice_sessions in the source horizon after an ok scrape run. Never from extractors."""
from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_session_use_cases import compute_price_minor
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
        dates = [draft.local_date for draft in drafts]
        lo, hi = min(dates), max(dates)
        await self._session.execute(
            text(
                """
                DELETE FROM ice_sessions
                WHERE arena_id = :arena_id
                  AND kind IN ('public_skate', 'open_ice')
                  AND local_date BETWEEN :lo AND :hi
                  AND (source_id IS NULL OR source_id NOT LIKE 'etalon_%')
                  AND (source_id IS NULL OR source_id <> 'admin')
                """
            ),
            {
                "arena_id": run.arena_id,
                "lo": lo,
                "hi": hi,
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
                    currency_code, session_label, age_note, external_url, status,
                    source_id, observed_at, valid_until
                ) VALUES (
                    :arena_id, :kind, :starts_at_utc, :ends_at_utc, :local_date,
                    :starts_at_local, :ends_at_local,
                    :price_adult_minor, :price_child_minor, :price_rental_minor, :price_minor,
                    :currency_code, :session_label, :age_note, :external_url, :status,
                    :source_id, :observed_at, :valid_until
                )
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
                "external_url": draft.external_url,
                "status": draft.status,
                "source_id": source_id,
                "observed_at": draft.observed_at,
                "valid_until": draft.valid_until,
            },
        )
