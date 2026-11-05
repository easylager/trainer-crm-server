"""Публикация ice_sessions после успешного прогона. Экстракторы сюда не пишут.

TASK-223: id сеанса стабилен между прогонами. В том же savepoint и том же окне
(``publish_horizon``):

* читаем будущие строки парсера арены — фильтр как у прежнего DELETE
  (``source_id IS NULL`` входит, ``admin`` и ``etalon_%`` нет);
* ключ ``(starts_at_utc, kind)`` есть и в базе, и в черновиках — UPDATE на месте;
* ключ только в черновиках — INSERT;
* ключ только в базе — DELETE (сеанс исчез из источника); при частично прочитанном
  источнике (``run.replace_dates``) — только в прочитанных датах;
* пустая (None/0) цена черновика не затирает известную цену строки (``keep_known_prices``).

Ручные ``admin``-сеансы (CMS-анонс до кассы): при совпадении ключа с черновиком
парсер **усыновляет** строку — ``schedule_basis=live``, ``external_url`` из кассы,
цены не затирает известные нулями, ``source_id`` остаётся ``admin`` (исчезновение
из ABWS не удалит анонс). ``etalon_%`` по-прежнему полностью защищены.

Пустые черновики и черновики целиком вне окна показа возвращают 0 и витрину
не обнуляют. ``ON CONFLICT DO NOTHING`` остаётся страховкой: гонка двух
прогонов и строка, которую фильтр чтения не захватил (уже закончилась сегодня,
но ключ ещё в ``uq_ice_sessions_parser_slot``).
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_session_use_cases import compute_price_minor
from src.ingestion.publish_diff import ExistingParserSession, plan_publish, slot_key
from src.ingestion.publish_horizon import PublishWindow, clip_to_publish_window, publish_window
from src.ingestion.scrape_runs import assert_can_replace_ice_sessions
from src.ingestion.types import PARSER_KINDS, RUN_STATUS_OK, CanonicalSlotDraft, ScrapeRunRecord
from src.shared.schedule_basis import SCHEDULE_BASIS_LIVE

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
        etalon_keys = await self._load_etalon_keys(run.arena_id, window)
        admin_by_key = await self._load_admin_by_key(run.arena_id, window)
        adopt: list[tuple[int, CanonicalSlotDraft]] = []
        plan_drafts: list[CanonicalSlotDraft] = []
        for draft in drafts:
            key = slot_key(draft.starts_at_utc, draft.kind)
            # Эталон не трогаем и не дублируем рядом.
            if key in etalon_keys:
                continue
            admin_id = admin_by_key.get(key)
            if admin_id is not None:
                adopt.append((admin_id, draft))
                continue
            plan_drafts.append(draft)
        # Savepoint: один плохой черновик откатывает только этот прогон, не весь тик.
        # _insert по-прежнему на каждую новую строку: тест устойчивости роняет его
        # посреди savepoint и проверяет, что соседняя джоба не теряется.
        async with self._session.begin_nested():
            # Журнал слотов: любое изменение отсюда — работа парсера. По source_id это не угадать:
            # адаптеры пишут туда свои идентификаторы (номер сеанса на сайте арены), а не «run:N».
            tag = "screenshot" if all(d.schedule_basis == "photo" for d in drafts) else "parser"
            await self._session.execute(
                text("SELECT set_config('app.change_source', :tag, true)"), {"tag": tag}
            )
            existing = await self._load_existing(run.arena_id, window)
            plan = plan_publish(existing, plan_drafts, replace_dates=run.replace_dates)
            await self._delete_ids(run.arena_id, plan.to_delete_ids)
            for session_id, draft in plan.to_update:
                await self._update(session_id, draft, scrape_run_id=run_id)
            for draft in plan.to_insert:
                await self._insert(draft, scrape_run_id=run_id)
            for session_id, draft in adopt:
                await self._adopt_admin(session_id, draft)
        # IndexNow: только если набор сеансов реально изменился (новые или исчезнувшие слоты).
        # UPDATE/adopt на месте не считаем: они идут на каждый прогон, даже без правок.
        if plan.to_insert or plan.to_delete_ids:
            from src.application.indexnow import notify_arena_changed

            await notify_arena_changed(self._session, run.arena_id)
        return len(plan_drafts) + len(adopt)

    async def _load_etalon_keys(self, arena_id: int, window: PublishWindow) -> set[tuple]:
        """Ключи эталонных слотов: парсер не усыновляет и не вставляет рядом."""
        result = await self._session.execute(
            text(f"""
                SELECT starts_at_utc, kind
                FROM ice_sessions
                WHERE arena_id = :arena_id
                  AND kind IN ({_PUBLISHABLE_KINDS_SQL})
                  AND status = 'active'
                  AND local_date >= :today
                  AND ends_at_utc > :now
                  AND source_id LIKE 'etalon_%'
                """),
            {"arena_id": arena_id, "today": window.today, "now": window.now},
        )
        return {slot_key(row["starts_at_utc"], str(row["kind"])) for row in result.mappings()}

    async def _load_admin_by_key(self, arena_id: int, window: PublishWindow) -> dict[tuple, int]:
        """Ручные слоты, которые касса может усыновить при совпадении ключа."""
        result = await self._session.execute(
            text(f"""
                SELECT id, starts_at_utc, kind
                FROM ice_sessions
                WHERE arena_id = :arena_id
                  AND kind IN ({_PUBLISHABLE_KINDS_SQL})
                  AND status = 'active'
                  AND local_date >= :today
                  AND ends_at_utc > :now
                  AND source_id = 'admin'
                ORDER BY id
                """),
            {"arena_id": arena_id, "today": window.today, "now": window.now},
        )
        out: dict[tuple, int] = {}
        for row in result.mappings():
            key = slot_key(row["starts_at_utc"], str(row["kind"]))
            # Несколько admin на один ключ — держим самый старый id.
            out.setdefault(key, int(row["id"]))
        return out

    async def _load_existing(self, arena_id: int, window: PublishWindow) -> list[ExistingParserSession]:
        """Будущие строки арены в видах парсера. Верхней границы даты нет.

        Сократившийся горизонт должен удалить дни за новым окном — их нет в
        черновиках, но они попадают в этот SELECT (``local_date >= сегодня``
        и ``ends_at_utc > now``) и уходят в ``to_delete_ids``.
        """
        result = await self._session.execute(
            text(f"""
                SELECT id, starts_at_utc, kind, status, source_id, local_date,
                       price_adult_minor, price_child_minor, price_rental_minor
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
                    local_date=row["local_date"],
                    price_adult_minor=row["price_adult_minor"],
                    price_child_minor=row["price_child_minor"],
                    price_rental_minor=row["price_rental_minor"],
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

    async def _adopt_admin(self, session_id: int, draft: CanonicalSlotDraft) -> None:
        """Касса увидела тот же слот: живой basis + ссылка, source_id остаётся admin.

        ``keep_known_prices``: NULL в черновике не затирает уже известную цену анонса.
        """
        current = (
            await self._session.execute(
                text(
                    """
                    SELECT price_adult_minor, price_child_minor, price_rental_minor,
                           session_label, age_note, capacity_note, hall, price_tiers, external_url
                    FROM ice_sessions
                    WHERE id = :id AND arena_id = :arena_id AND source_id = 'admin'
                    """
                ),
                {"id": session_id, "arena_id": draft.arena_id},
            )
        ).mappings().first()
        if current is None:
            return
        adult = draft.price_adult_minor if draft.price_adult_minor is not None else current["price_adult_minor"]
        child = draft.price_child_minor if draft.price_child_minor is not None else current["price_child_minor"]
        rental = draft.price_rental_minor if draft.price_rental_minor is not None else current["price_rental_minor"]
        await self._session.execute(
            text(
                """
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
                    hall = :hall,
                    price_tiers = CAST(:price_tiers AS jsonb),
                    external_url = :external_url,
                    status = :status,
                    source_id = 'admin',
                    observed_at = :observed_at,
                    valid_until = :valid_until,
                    schedule_basis = :schedule_basis
                WHERE id = :id
                  AND arena_id = :arena_id
                  AND source_id = 'admin'
                """
            ),
            {
                "id": session_id,
                "arena_id": draft.arena_id,
                "ends_at_utc": draft.ends_at_utc,
                "local_date": draft.local_date,
                "starts_at_local": draft.starts_at_local,
                "ends_at_local": draft.ends_at_local,
                "price_adult_minor": adult,
                "price_child_minor": child,
                "price_rental_minor": rental,
                "price_minor": compute_price_minor(adult, child, rental),
                "currency_code": draft.currency_code,
                "session_label": draft.session_label if draft.session_label is not None else current["session_label"],
                "age_note": draft.age_note if draft.age_note is not None else current["age_note"],
                "capacity_note": draft.capacity_note if draft.capacity_note is not None else current["capacity_note"],
                "hall": draft.hall if draft.hall is not None else current["hall"],
                "price_tiers": (
                    json.dumps(draft.price_tiers, ensure_ascii=False)
                    if draft.price_tiers
                    else json.dumps(current["price_tiers"], ensure_ascii=False)
                    if current["price_tiers"] is not None
                    else None
                ),
                "external_url": draft.external_url if draft.external_url else current["external_url"],
                "status": draft.status,
                "observed_at": draft.observed_at,
                "valid_until": draft.valid_until,
                "schedule_basis": draft.schedule_basis or SCHEDULE_BASIS_LIVE,
            },
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
                    hall = :hall,
                    price_tiers = CAST(:price_tiers AS jsonb),
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
                    currency_code, session_label, age_note, capacity_note, hall, price_tiers, external_url, status,
                    source_id, observed_at, valid_until, schedule_basis
                ) VALUES (
                    :arena_id, :kind, :starts_at_utc, :ends_at_utc, :local_date,
                    :starts_at_local, :ends_at_local,
                    :price_adult_minor, :price_child_minor, :price_rental_minor, :price_minor,
                    :currency_code, :session_label, :age_note, :capacity_note, :hall, CAST(:price_tiers AS jsonb), :external_url, :status,
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
            "hall": draft.hall,
            "price_tiers": json.dumps(draft.price_tiers, ensure_ascii=False) if draft.price_tiers else None,
            "external_url": draft.external_url,
            "status": draft.status,
            "source_id": source_id,
            "observed_at": draft.observed_at,
            "valid_until": draft.valid_until,
            "schedule_basis": draft.schedule_basis,
        }
