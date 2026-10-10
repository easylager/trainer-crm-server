"""Публикация ice_sessions после успешного прогона. Экстракторы сюда не пишут.

TASK-223: id сеанса стабилен между прогонами. В том же savepoint и том же окне
(``publish_horizon``):

* читаем будущие строки парсера арены — фильтр как у прежнего DELETE
  (``source_id IS NULL`` входит, ``admin`` и ``etalon_%`` нет);
* ключ ``(starts_at_utc, kind)`` есть и в базе, и в черновиках — UPDATE на месте;
* ключ только в черновиках — INSERT;
* ключ только в базе — DELETE (сеанс исчез из источника).

Пустые черновики и черновики целиком вне окна показа возвращают 0 и витрину
не обнуляют. ``ON CONFLICT DO NOTHING`` остаётся страховкой: гонка двух
прогонов и строка, которую фильтр чтения не захватил (уже закончилась сегодня,
но ключ ещё в ``uq_ice_sessions_parser_slot``).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_session_use_cases import compute_price_minor
from src.ingestion.publish_diff import ExistingParserSession, plan_publish
from src.ingestion.publish_horizon import PublishWindow, clip_to_publish_window, publish_window
from src.ingestion.scrape_runs import assert_can_replace_ice_sessions
from src.ingestion.types import PARSER_KINDS, RUN_STATUS_OK, CanonicalSlotDraft, ScrapeRunRecord

_PUBLISHABLE_KINDS_SQL = ", ".join(f"'{kind}'" for kind in PARSER_KINDS)

# 1:1 с прежним DELETE. NULL заменяется; admin и LIKE 'etalon_%' — нет.
# Семантика шаблона (``_`` — один символ) — в is_replaceable_parser_row.
_REPLACEABLE_SOURCE_SQL = """
  AND (source_id IS NULL OR source_id NOT LIKE 'etalon_%')
  AND (source_id IS NULL OR source_id <> 'admin')
"""


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
        # Savepoint: один плохой черновик откатывает только этот прогон, не весь тик.
        # _insert по-прежнему на каждую новую строку: тест устойчивости роняет его
        # посреди savepoint и проверяет, что соседняя джоба не теряется.
        async with self._session.begin_nested():
            existing = await self._load_existing(run.arena_id, window)
            plan = plan_publish(existing, drafts)
            await self._delete_ids(run.arena_id, plan.to_delete_ids)
            for session_id, draft in plan.to_update:
                await self._update(session_id, draft, scrape_run_id=run_id)
            for draft in plan.to_insert:
                await self._insert(draft, scrape_run_id=run_id)
        return len(drafts)

    async def _load_existing(self, arena_id: int, window: PublishWindow) -> list[ExistingParserSession]:
        """Будущие строки арены в видах парсера. Верхней границы даты нет.

        Сократившийся горизонт должен удалить дни за новым окном — их нет в
        черновиках, но они попадают в этот SELECT (``local_date >= сегодня``
        и ``ends_at_utc > now``) и уходят в ``to_delete_ids``.
        """
        result = await self._session.execute(
            text(f"""
                SELECT id, starts_at_utc, kind, status, source_id
                FROM ice_sessions
                WHERE arena_id = :arena_id
                  AND kind IN ({_PUBLISHABLE_KINDS_SQL})
                  AND local_date >= :today
                  AND ends_at_utc > :now
                  {_REPLACEABLE_SOURCE_SQL}
                ORDER BY id
                """),
            {"arena_id": arena_id, "today": window.today, "now": window.now},
        )
        rows: list[ExistingParserSession] = []
        for row in result.mappings():
            rows.append(
                ExistingParserSession(
                    id=int(row["id"]),
                    starts_at_utc=row["starts_at_utc"],
                    kind=str(row["kind"]),
                    source_id=row["source_id"],
                    status=str(row["status"] or "active"),
                )
            )
        return rows

    async def _delete_ids(self, arena_id: int, ids: tuple[int, ...]) -> None:
        if not ids:
            return
        await self._session.execute(
            text(f"""
                DELETE FROM ice_sessions
                WHERE arena_id = :arena_id
                  AND id = ANY(:ids)
                  AND kind IN ({_PUBLISHABLE_KINDS_SQL})
                  {_REPLACEABLE_SOURCE_SQL}
                """),
            {"arena_id": arena_id, "ids": [int(session_id) for session_id in ids]},
        )

    async def _update(self, session_id: int, draft: CanonicalSlotDraft, *, scrape_run_id: int | None) -> None:
        """Поля слота на месте. id, arena_id, kind, starts_at_utc не трогаем — это ключ."""
        params = self._params(draft, scrape_run_id=scrape_run_id)
        params["id"] = session_id
        await self._session.execute(
            text(f"""
                UPDATE ice_sessions SET
                    ends_at_utc = :ends_at_utc,
                    local_date = :local_date,
                    starts_at_local = :starts_at_local,
                    ends_at_local = :ends_at_local,
                    price_adult_minor = :price_adult_minor,
                    price_child_minor = :price_child_minor,
                    price_rental_minor = :price_rental_minor,
                    price_minor = :price_minor,
                    currency_code = :currency_code,
                    session_label = :session_label,
                    age_note = :age_note,
                    capacity_note = :capacity_note,
                    external_url = :external_url,
                    status = :status,
                    source_id = :source_id,
                    observed_at = :observed_at,
                    valid_until = :valid_until,
                    schedule_basis = :schedule_basis
                WHERE id = :id
                  AND arena_id = :arena_id
                  {_REPLACEABLE_SOURCE_SQL}
                """),
            params,
        )

    async def _insert(self, draft: CanonicalSlotDraft, *, scrape_run_id: int | None) -> None:
        params = self._params(draft, scrape_run_id=scrape_run_id)
        await self._session.execute(
            text("""
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
                """),
            params,
        )

    def _params(self, draft: CanonicalSlotDraft, *, scrape_run_id: int | None) -> dict:
        source_id = draft.source_id
        if source_id is None and scrape_run_id is not None:
            source_id = f"run:{scrape_run_id}:{draft.starts_at_local}"
        return {
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
            "price_minor": compute_price_minor(
                draft.price_adult_minor, draft.price_child_minor, draft.price_rental_minor
            ),
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
        }
