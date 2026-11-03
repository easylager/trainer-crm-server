"""План публикации сеансов парсера без смены id (TASK-223).

Естественный ключ внутри одной арены — ``(starts_at_utc, kind)``
(частичный уникальный индекс ``uq_ice_sessions_parser_slot``). Функция чистая:
вызывающий сам читает строки тем же фильтром, что прежний DELETE в ``publish``.

Пустой список черновиков означает «удалить все переданные заменяемые строки».
Публикатор так не вызывает план: пустой прогон и окно без черновиков возвращают 0
и витрину не трогают.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Sequence

from src.ingestion.types import CanonicalSlotDraft

# LIKE 'etalon_%': «etalon» + один любой символ + хвост. ``_`` в LIKE — не литерал.
_ETALON_LIKE_PREFIX = "etalon"
_ETALON_LIKE_MIN_LEN = len(_ETALON_LIKE_PREFIX) + 1


@dataclass(frozen=True)
class ExistingParserSession:
    """Строка ice_sessions, которую публикатор уже отобрал фильтром замены."""

    id: int
    starts_at_utc: datetime
    kind: str
    source_id: str | None = None
    status: str = "active"
    local_date: date | None = None
    price_adult_minor: int | None = None
    price_child_minor: int | None = None
    price_rental_minor: int | None = None


@dataclass(frozen=True)
class PublishPlan:
    """Что сделать в одном savepoint. ``to_update`` — пары (id существующей строки, черновик)."""

    to_insert: tuple[CanonicalSlotDraft, ...]
    to_update: tuple[tuple[int, CanonicalSlotDraft], ...]
    to_delete_ids: tuple[int, ...]


def is_replaceable_parser_row(source_id: str | None) -> bool:
    """Совпадает с фильтром DELETE/SELECT в ``publish``.

    ``source_id IS NULL`` заменяется (так фильтр написан сегодня: оба предиката
    истинны через ``IS NULL OR``). ``admin`` и шаблон ``etalon_%`` — нет.
    В SQL ``_`` внутри LIKE — один любой символ, поэтому исключается любой
    ``source_id``, который начинается с ``etalon`` и длиннее на хотя бы один
    символ (``etalon_…`` и ``etalonX…``). Более короткий (просто ``etalon``)
    под шаблон не попадает и заменяется.
    """
    if source_id is None:
        return True
    if source_id == "admin":
        return False
    if len(source_id) >= _ETALON_LIKE_MIN_LEN and source_id.startswith(_ETALON_LIKE_PREFIX):
        return False
    return True


def slot_key(starts_at_utc: datetime, kind: str) -> tuple[datetime, str]:
    """Ключ слота. Одинаковый момент в разных tzinfo — один слот."""
    if starts_at_utc.tzinfo is None:
        moment = starts_at_utc
    else:
        moment = starts_at_utc.astimezone(timezone.utc)
    return (moment, kind)


_PRICE_FIELDS = ("price_adult_minor", "price_child_minor", "price_rental_minor")


def _known_price(value: int | None) -> bool:
    return value is not None and int(value) > 0


def keep_known_prices(row: ExistingParserSession, draft: CanonicalSlotDraft) -> CanonicalSlotDraft:
    """A run never erases a price: an empty (None/0) price in the draft keeps the stored one.

    A broken price block (site redesign, OCR miss) yields None or 0 for every slot; writing that
    over a known price hides it from visitors and from price filters. A real change is a positive
    number and still wins. Known limit: a session that really became free (0) keeps its old price
    until an admin edits it — no parser emits 0 for «free» today.
    """
    changes = {
        name: getattr(row, name)
        for name in _PRICE_FIELDS
        if not _known_price(getattr(draft, name)) and _known_price(getattr(row, name))
    }
    return replace(draft, **changes) if changes else draft


def plan_publish(
    existing: Sequence[ExistingParserSession],
    drafts: Sequence[CanonicalSlotDraft],
    *,
    replace_dates: frozenset[date] | None = None,
) -> PublishPlan:
    """Свести текущие строки и черновики по ``(starts_at_utc, kind)``.

    Совпавший ключ — UPDATE самой старой строки (меньший id), лишние дубли
    ключа — в удаление. Ключ только в черновиках — INSERT (первый черновик
    побеждает, как ``ON CONFLICT DO NOTHING``). Ключ только в базе — DELETE.
    ``admin`` / ``etalon_%`` в план не попадают, даже если их передали.
    Статус в UPDATE всегда берётся из черновика: ``expired`` / ``cancelled`` /
    ``superseded`` снова становятся ``active``, если источник вернул сеанс.

    ``replace_dates``: источник прочитан не целиком (например, афиша, где одна колонка не
    распозналась). Удаляются только строки этих дат; остальные дни остаются как были —
    нечитаемый день не должен стирать уже опубликованные сеансы. ``None`` — как раньше.
    Цены в UPDATE проходят ``keep_known_prices``: пустая цена черновика не затирает известную.
    """
    by_key: dict[tuple[datetime, str], list[ExistingParserSession]] = {}
    for row in existing:
        if not is_replaceable_parser_row(row.source_id):
            continue
        by_key.setdefault(slot_key(row.starts_at_utc, row.kind), []).append(row)

    seen: set[tuple[datetime, str]] = set()
    to_insert: list[CanonicalSlotDraft] = []
    to_update: list[tuple[int, CanonicalSlotDraft]] = []
    matched: set[tuple[datetime, str]] = set()

    for draft in drafts:
        key = slot_key(draft.starts_at_utc, draft.kind)
        if key in seen:
            continue
        seen.add(key)
        rows = by_key.get(key)
        if not rows:
            to_insert.append(draft)
            continue
        matched.add(key)
        keeper = min(rows, key=lambda row: row.id)
        to_update.append((keeper.id, keep_known_prices(keeper, draft)))

    to_delete: list[int] = []
    for key, rows in by_key.items():
        if key in matched:
            keeper_id = min(row.id for row in rows)
            to_delete.extend(row.id for row in rows if row.id != keeper_id)
        elif replace_dates is None:
            to_delete.extend(row.id for row in rows)
        else:
            to_delete.extend(
                row.id for row in rows if row.local_date is not None and row.local_date in replace_dates
            )

    return PublishPlan(
        to_insert=tuple(to_insert),
        to_update=tuple(to_update),
        to_delete_ids=tuple(sorted(to_delete)),
    )
