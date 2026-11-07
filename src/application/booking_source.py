"""Источник записи (TASK-351): откуда пришёл человек, который записался сам.

У записи — стабильный короткий код (``bookings.source``) и, где есть, место
(``source_arena_id`` / ``source_city_id``). Код не меняется задним числом: срез «за 30 дней»
сравним с прошлым.

Как источник доезжает до записи:

* **Сайт → Telegram.** Ссылка на страницу тренера несёт метку ``?via=`` (``p<каток>``,
  ``c<город>``, ``k<город>``; без метки — пришли прямо на ``/t/``). Кнопка «Записаться» кладёт
  её в ``startapp`` хвостом ``_v_<метка>``: ``trainer_7_v_p3``. Mini App получает этот
  параметр в подписанной initData.
* **Бот.** Ссылка тренера (``welcome_ref``) и рекомендация (``share_ref``) приходят в бота;
  кнопка бота открывает Mini App с ``?via=link`` / ``?via=share`` в адресе.
* **Mini App.** ``booking-client.js`` запоминает источник на время сеанса и кладёт его
  в тело записи. Сервер проверяет код; если клиент его не прислал (старый кэш), берёт из
  подписанного ``start_param``. Неизвестно откуда — ``unknown``: запись всё равно создаётся.

Один сеанс Mini App — один источник (первое касание). Человек, пришедший с катка и
записавшийся к другому тренеру, остаётся «со страницы катка».
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Ссылка тренера ученикам (``/t/…?via=link`` → ``welcome_ref``).
SOURCE_LINK = "link"
#: «Поделиться тренером» из Mini App (``/t/…?via=share`` → ``share_ref``).
SOURCE_SHARE = "share"
#: Страница катка ``/p/…`` → страница тренера → запись.
SOURCE_SITE_PLACE = "site_place"
#: Страница города ``/c/{город}``.
SOURCE_SITE_CITY = "site_city"
#: Каталог тренеров сайта ``/c/{город}/trenery[/{направление}]`` (страницы ещё нет).
SOURCE_SITE_CATALOG = "site_catalog"
#: Страница тренера ``/t/…`` без другой метки (поиск, прямой заход).
SOURCE_SITE_TRAINER = "site_trainer"
#: Выбрали тренера в Mini App: список каталога, карточка катка, витрина.
SOURCE_MINIAPP = "miniapp"
#: Записался сам, но откуда пришёл — не известно (меню бота, старый клиент).
SOURCE_UNKNOWN = "unknown"

BOOKING_SOURCES = (
    SOURCE_LINK,
    SOURCE_SHARE,
    SOURCE_SITE_PLACE,
    SOURCE_SITE_CITY,
    SOURCE_SITE_CATALOG,
    SOURCE_SITE_TRAINER,
    SOURCE_MINIAPP,
    SOURCE_UNKNOWN,
)
_BOOKING_SOURCE_SET = frozenset(BOOKING_SOURCES)

#: Подписи для админского среза.
BOOKING_SOURCE_LABEL_RU = {
    SOURCE_LINK: "Ссылка тренера",
    SOURCE_SHARE: "Рекомендация",
    SOURCE_SITE_PLACE: "Страница катка",
    SOURCE_SITE_CITY: "Страница города",
    SOURCE_SITE_CATALOG: "Каталог сайта",
    SOURCE_SITE_TRAINER: "Страница тренера",
    SOURCE_MINIAPP: "Mini App",
    SOURCE_UNKNOWN: "Не известно",
}

#: Метка места в ``?via=`` и в хвосте ``startapp``: буква — вид места, число — id.
_VIA_PLACE_KINDS = {"p": SOURCE_SITE_PLACE, "c": SOURCE_SITE_CITY, "k": SOURCE_SITE_CATALOG}
_VIA_TOKEN_RE = re.compile(r"^([pck])([1-9][0-9]{0,8})$")
_MAX_ID = 2**31 - 1


@dataclass(frozen=True)
class BookingSource:
    code: str
    arena_id: int | None = None
    city_id: int | None = None

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.code}
        if self.arena_id is not None:
            out["source_arena_id"] = self.arena_id
        if self.city_id is not None:
            out["source_city_id"] = self.city_id
        return out


def place_via(*, arena_id: int | None = None, city_id: int | None = None, catalog: bool = False) -> str | None:
    """Метка для ссылки на ``/t/``: ``p3`` (каток), ``c1`` (город), ``k1`` (каталог города)."""
    if arena_id is not None and int(arena_id) > 0:
        return f"p{int(arena_id)}"
    if city_id is not None and int(city_id) > 0:
        return f"{'k' if catalog else 'c'}{int(city_id)}"
    return None


def clean_place_via(raw: str | None) -> str | None:
    """Метка места из запроса или ``None``: ``link`` / ``share`` / мусор сюда не проходят."""
    token = (raw or "").strip().lower()
    return token if _VIA_TOKEN_RE.match(token) else None


def source_from_via(raw: str | None) -> BookingSource | None:
    """``?via=`` страницы тренера или адреса Mini App → источник; неизвестное → ``None``."""
    token = (raw or "").strip().lower()
    if token == SOURCE_LINK:
        return BookingSource(SOURCE_LINK)
    if token == SOURCE_SHARE:
        return BookingSource(SOURCE_SHARE)
    m = _VIA_TOKEN_RE.match(token)
    if m is None:
        return None
    code = _VIA_PLACE_KINDS[m.group(1)]
    place_id = int(m.group(2))
    if code == SOURCE_SITE_PLACE:
        return BookingSource(code, arena_id=place_id)
    return BookingSource(code, city_id=place_id)


def source_from_start_param(start_param: str | None) -> BookingSource | None:
    """Источник по ``startapp``, с которым открыли Mini App.

    * ``trainer_7_v_p3`` / ``_v_c1`` / ``_v_k1`` — со страницы тренера, куда пришли с катка /
      города / каталога;
    * ``trainer_7`` — прямо со страницы тренера; ``trainer_7_a_3`` — старая ссылка строки тренера
      на странице катка (до TASK-350);
    * ``catalog_<город>_coach`` — «Все тренеры» со страницы города.

    Остальные параметры (каток, матч, лига) источник записи не задают.
    """
    from src.application.place_links import parse_catalog_start_param, parse_trainer_start_param

    sp = (start_param or "").strip()
    if not sp:
        return None
    coach = parse_trainer_start_param(sp)
    if coach is not None:
        arena_id, via = coach["arena_id"], coach["via"]
        if via:
            return source_from_via(via)
        if arena_id is not None:
            return BookingSource(SOURCE_SITE_PLACE, arena_id=arena_id)
        return BookingSource(SOURCE_SITE_TRAINER)
    target = parse_catalog_start_param(sp)
    if target is not None and target[0] is not None and target[1] == "coach":
        return BookingSource(SOURCE_SITE_CITY, city_id=int(target[0]))
    return None


def _clean_id(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= _MAX_ID else None


def clean_booking_source(code: str | None, *, arena_id: Any = None, city_id: Any = None) -> BookingSource | None:
    """Источник из тела записи: неизвестный код → ``None`` (запись не падает), чужие id отбрасываются.

    Каток бывает только у ``site_place`` и ``miniapp``, город — у сайта и Mini App.
    """
    c = (code or "").strip().lower()
    if c not in _BOOKING_SOURCE_SET:
        return None
    arena = _clean_id(arena_id) if c in (SOURCE_SITE_PLACE, SOURCE_MINIAPP) else None
    city = (
        _clean_id(city_id) if c in (SOURCE_SITE_PLACE, SOURCE_SITE_CITY, SOURCE_SITE_CATALOG, SOURCE_MINIAPP) else None
    )
    return BookingSource(c, arena_id=arena, city_id=city)


def resolve_booking_source(
    *,
    body_source: str | None,
    body_arena_id: Any = None,
    body_city_id: Any = None,
    signed_start_param: str | None = None,
) -> BookingSource:
    """Что записать в ``bookings.source`` для записи клиента из Mini App.

    Тело (его собирает ``booking-client.js``) → подписанный ``start_param`` → ``unknown``.
    """
    from_body = clean_booking_source(body_source, arena_id=body_arena_id, city_id=body_city_id)
    if from_body is not None:
        return from_body
    return source_from_start_param(signed_start_param) or BookingSource(SOURCE_UNKNOWN)


# ── Срез для админа ──────────────────────────────────────────────────


async def get_booking_source_breakdown(session: Any, *, as_of: Any = None) -> dict[str, Any]:
    """Записи и «Написать в Telegram» по источникам за 7 и 30 дней — админское «Сейчас».

    Записи — сами записавшиеся клиенты (``source`` не NULL), без демо-записей онбординга,
    по дате создания, отменённые тоже: это спрос. «Написать» — нажатия на сайте, люди без ботов
    и служебных аккаунтов, один человек — одно нажатие тренеру за сутки.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from src.application.catalog_consumer_events import KIND_PUBLIC_CONTACT_CLICK, catalog_actor_exclusion_sql

    now = as_of or datetime.now(timezone.utc)
    since_7, since_30 = now - timedelta(days=7), now - timedelta(days=30)
    params = {"now": now, "s7": since_7, "s30": since_30}
    counts: dict[str, dict[str, int]] = {}

    def bucket(code: str | None) -> dict[str, int]:
        key = code if code in _BOOKING_SOURCE_SET else SOURCE_UNKNOWN
        return counts.setdefault(key, {"bookings_7d": 0, "bookings_30d": 0, "writes_7d": 0, "writes_30d": 0})

    booking_rows = (
        await session.execute(
            text("""
                SELECT b.source,
                       COUNT(*) FILTER (WHERE b.created_at >= :s7)::int AS n7,
                       COUNT(*)::int AS n30
                FROM bookings b
                WHERE b.source IS NOT NULL
                  AND NOT b.is_sandbox
                  AND b.created_at >= :s30 AND b.created_at < :now
                GROUP BY b.source
                """),
            params,
        )
    ).all()
    for code, n7, n30 in booking_rows:
        row = bucket(code)
        row["bookings_7d"] += int(n7 or 0)
        row["bookings_30d"] += int(n30 or 0)

    ex_sql, ex_params = catalog_actor_exclusion_sql("e.actor_hash")
    write_rows = (
        await session.execute(
            text(f"""
                SELECT e.payload->>'source' AS source,
                       COUNT(*) FILTER (WHERE e.occurred_at >= :s7)::int AS n7,
                       COUNT(*)::int AS n30
                FROM catalog_consumer_events e
                WHERE e.kind = :kind
                  AND e.payload->>'action' = 'telegram'
                  AND COALESCE(e.payload->>'ua_class', 'human') = 'human'
                  AND e.occurred_at >= :s30 AND e.occurred_at < :now
                  {ex_sql}
                GROUP BY 1
                """),
            {**params, "kind": KIND_PUBLIC_CONTACT_CLICK, **ex_params},
        )
    ).all()
    for code, n7, n30 in write_rows:
        row = bucket(code)
        row["writes_7d"] += int(n7 or 0)
        row["writes_30d"] += int(n30 or 0)

    rows: list[dict[str, Any]] = [
        {"source": code, "label": BOOKING_SOURCE_LABEL_RU[code], **counts[code]}
        for code in BOOKING_SOURCES
        if code in counts
    ]
    totals = {k: sum(counts[c][k] for c in counts) for k in ("bookings_7d", "bookings_30d", "writes_7d", "writes_30d")}
    return {"metric": "booking_sources", "as_of": now.isoformat(), "rows": rows, "totals": totals}
