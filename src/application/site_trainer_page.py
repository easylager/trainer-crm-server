"""Страница тренера на сайте ``/t/{id}-{slug}`` — пара к странице катка ``/p/{city}/{slug}``.

Одна ссылка на человека: её тренер отправляет родителям, её открывают в браузере, её находит поиск.
Логика — карточки тренера в Mini App, своих правил у сайта нет:

* кто виден людям — ``trainer_is_listed`` / ``CATALOG_LISTED_SQL`` (как ``/api/public/trainers/{id}``);
* «Записаться» — только при ``can_book`` (подписка с онлайн-записью, PDEC-025); без неё — «Написать»;
* время — те же свободные слоты, что «Ближайшие окна» на карточке катка (``_trainer_windows_on_arena``),
  по всем площадкам, на неделю с сегодняшнего дня;
* направления (вкладки карточки цены) — ``catalog_directions``, цены — только тарифы услуг.

Дизайн — PDEC-033, ``.ai/epics/trainer-catalog/design/trainer.html`` (TASK-356): первый экран —
фото, имя, галочки из анкеты и тёмная карточка цены с ближайшим временем. Число занятий не
показываем никогда, оценку — от 3 оценок, слова тренера — дословно, нет данных — нет блока.

Тренер не в каталоге (черновик, снят, пауза) — страница по его прямой ссылке открывается, но
``noindex``, её нет в sitemap и на страницах катков: «запись по вашей ссылке работает как обычно».
Деактивированного тренера нет совсем — 404.

Адрес — как у матча ``/m/{id}-{slug}``: решает id, хвост для людей; неверный хвост → 301.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.style_b import _file_version
from src.application.catalog_directions import (
    DIRECTIONS,
    Direction,
    catalog_path,
    direction_by_key,
    load_service_directions,
    service_direction,
    service_title,
)
from src.application.ice_city_day import city_slug, format_price_minor, human_date, plural_ru
from src.application.place_links import place_page_url, public_telegram_cta_url, trainer_start_param
from src.application.site_trainers import trainer_initial, trainer_line, trainer_name, trainer_photo_url
from src.application.style_b import esc
from src.shared.catalog_visibility import CATALOG_LISTED_SQL, trainer_is_listed
from src.shared.city_locative import city_locative
from src.shared.html_template import fill_placeholders

TRAINER_PREFIX = "/t"
TRAINER_SURFACE = "trainer_page"
_B_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"
_TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
TITLE_LIMIT = 60
DESCRIPTION_LIMIT = 155
#: Ближайшее время в карточке цены — дальше «Всё время на неделю».
NEAR_SHOWN = 3
#: Слотов на неделю с запасом: у тренера с плотным расписанием их бывает десятки.
#: Окон на тренера в выборке: 7 дней по ~10 слотов с запасом — общий лимит не должен съедать конец недели.
WEEK_WINDOWS_LIMIT = 200
#: Как далеко вперёд ищем окна: неделя сетки стартует с первого дня с окнами, он может быть не сегодня.
WEEK_LOOKAHEAD_DAYS = 14
WEEK_DAYS = 7
#: Оценку показываем, когда оценок хотя бы столько (решение владельца).
RATING_MIN_COUNT = 3
#: Сколько других тренеров направления показываем внизу.
PEERS_SHOWN = 6
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


# ── Адрес ────────────────────────────────────────────────────────────


def trainer_slug(trainer_id: int, name: str) -> str:
    """``9-aleksandr-gaevskiy``: id решает, имя — для людей и поиска. Без имени — просто id."""
    tail = city_slug(name) if name and name != "Тренер" else ""
    return f"{int(trainer_id)}-{tail}" if tail else str(int(trainer_id))


def trainer_path(trainer_id: int, name: str) -> str:
    return f"{TRAINER_PREFIX}/{trainer_slug(trainer_id, name)}"


def trainer_page_url(base_url: str, trainer_id: int, name: str) -> str:
    return f"{(base_url or '').rstrip('/')}{trainer_path(trainer_id, name)}"


def parse_trainer_ref(ref: str) -> int | None:
    head = (ref or "").split("-", 1)[0]
    return int(head) if head.isdigit() and 0 < int(head) < 2**31 else None


# ── Цены — только тарифы услуги ──────────────────────────────────────

#: Подписи тарифов для людей (вид тарифа — ``price_tier_kind``, их ровно пять) в порядке прототипа.
_TIER_LABELS: tuple[tuple[str, str], ...] = (
    ("child", "Ребёнок"),
    ("adult", "Взрослый"),
    ("two_children", "Двое детей"),
    ("adult_and_child", "Взрослый + ребёнок"),
    ("two_adults", "Двое взрослых"),
)
_KID_KINDS = frozenset({"child", "two_children", "adult_and_child"})
_ADULT_KINDS = frozenset({"adult", "two_adults", "adult_and_child"})


def _money(cents: int, currency: str) -> str:
    return format_price_minor(int(cents), currency).replace(" ", " ")


def _tier_cents(svc: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for t in svc.get("price_tiers") or []:
        try:
            cents = int(t.get("price_cents") or 0)
        except (TypeError, ValueError):
            continue
        if cents > 0 and t.get("tier_kind"):
            out.setdefault(str(t["tier_kind"]), cents)
    return out


def service_prices(svc: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Все тарифы услуги строками «Цены»: [(подпись, сумма)]. Без тарифов — цена услуги «Занятие»."""
    cur = str(svc.get("currency_code") or "BYN")
    tiers = _tier_cents(svc)
    if tiers:
        return [(label, _money(tiers[kind], cur)) for kind, label in _TIER_LABELS if kind in tiers]
    try:
        cents = int(svc.get("price_cents") or 0)
    except (TypeError, ValueError):
        cents = 0
    return [("Занятие", _money(cents, cur))] if cents > 0 else []


def card_prices(svc: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Цена в карточке: ребёнок и взрослый (равны — одной строкой); «на двоих» — в «Ценах».

    Только тарифы «на двоих» — показываем их, иначе карточка соврала бы «цену уточните».
    """
    cur = str(svc.get("currency_code") or "BYN")
    tiers = _tier_cents(svc)
    child, adult = tiers.get("child"), tiers.get("adult")
    if child and adult and child == adult:
        return [("Дети и взрослые", _money(child, cur))]
    single = [(label, _money(tiers[k], cur)) for k, label in _TIER_LABELS[:2] if k in tiers]
    return single or service_prices(svc)


def _audience(services: Sequence[Mapping[str, Any]]) -> str:
    """«Дети и взрослые.» — только когда в тарифах есть и детский, и взрослый вид.

    Один «Взрослый» ничего не говорит: это вид тарифа по умолчанию у старых цен.
    """
    kinds = {k for s in services for k in _tier_cents(s)}
    kids, adults = bool(kinds & _KID_KINDS), bool(kinds & _ADULT_KINDS)
    if kids and adults:
        return "Дети и взрослые."
    if kids and not adults:
        return "Дети."
    return ""


def _role_line(directions: Sequence[Direction]) -> str:
    """«Занятия с нуля и для уже катающихся.» — из направлений тренера, словами направления.

    Роли однотипные («с нуля», «для уже катающихся», «по фигурному катанию»), поэтому склеиваются
    после существительного «Занятия» без согласования падежей.
    """
    parts = [d.role for d in directions if d.role]
    if not parts:
        return ""
    phrase = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " и " + parts[-1]
    return f"Занятия {phrase}."


_NOTICE_PREFIX = re.compile(r"^\s*в\s+(?:стоимость|цену)\s+не\s+вход(?:ят|ит)\s*[:\-–—]?\s*", re.IGNORECASE)


def _notice_text(raw: Any) -> str:
    """Заметка тренера «в цену не входит» без своего зачина — над ней уже стоит подпись «Не входит в цену»."""
    text_ = str(raw or "").strip()
    return _NOTICE_PREFIX.sub("", text_, count=1).strip() or text_


def _service_view(svc: Mapping[str, Any]) -> dict[str, Any]:
    name = str(svc.get("service_name") or "").strip()
    return {
        "name": name,
        "title": service_title(name),
        "hook": str(svc.get("summary_hook") or "").strip(),
        "body": str(svc.get("summary_body") or "").strip(),
        "notice": _notice_text(svc.get("client_notice")),
        "description": str(svc.get("description") or "").strip(),
        "prices": service_prices(svc),
        "card_prices": card_prices(svc),
        "pair": "adult_and_child" in _tier_cents(svc),
        "min": _min_cents(svc),
    }


def _min_cents(svc: Mapping[str, Any]) -> int | None:
    """Цена услуги «от» в её карточке: тарифы, без тарифов — цена услуги (групповая и абонементы — нет)."""
    from src.application.trainer_min_price import service_price_from

    return service_price_from(svc)


def group_services(services: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(направления тренера по порядку вкладок, «Ещё ведёт» — услуги без вкладки).

    Услуги внутри направления — в порядке ``service_ids`` направления, своя услуга — после них.
    """
    by_dir: dict[str, list[Mapping[str, Any]]] = {}
    other: list[dict[str, Any]] = []
    for svc in services:
        if not str(svc.get("service_name") or "").strip():
            continue
        key = service_direction(svc)
        if key:
            by_dir.setdefault(key, []).append(svc)
        else:
            other.append(_service_view(svc))
    dirs: list[dict[str, Any]] = []
    for d in DIRECTIONS:
        svcs = by_dir.get(d.key)
        if not svcs:
            continue
        order = d.service_ids
        svcs = sorted(svcs, key=lambda s: order.index(int(s["service_id"])) if int(s["service_id"]) in order else 99)
        views = [_service_view(s) for s in svcs]
        for v, s in zip(views, svcs):
            # Своя услуга во вкладке — со своим названием: это слова тренера, не наше направление.
            v["own"] = int(s["service_id"]) not in order
        dirs.append({"key": d.key, "tab": d.tab, "services": views, "raw": svcs})
    return dirs, other


# ── Данные ───────────────────────────────────────────────────────────

_EDUCATION_LINE = {
    "Среднее специальное": "Среднее специальное образование",
    "Высшее профильное": "Высшее профильное образование",
    "Высшее непрофильное": "Высшее непрофильное образование",
    "Курсы и сертификация": "Курсы и сертификация",
    "Ученая степень": "Учёная степень",
}


def education_line(value: Any) -> str:
    """Категория из анкеты строкой галочки; «Другое» и свободный текст на карточку не выносим."""
    return _EDUCATION_LINE.get(str(value or "").strip(), "")


def contact_url(trainer_id: int, telegram_username: str | None, *, listed: bool) -> str | None:
    """«Написать в Telegram»: у тренера в каталоге — учётный ``/r/tg/{id}``, иначе прямой ``t.me``.

    Тот же выбор, что ``contact_telegram_url`` у ``/api/public/trainers/{id}``: ``/r/tg`` отвечает 404
    всем, кого нет в каталоге.
    """
    handle = (telegram_username or "").strip().lstrip("@")
    if not handle or not _TELEGRAM_USERNAME_RE.fullmatch(handle):
        return None
    return f"/r/tg/{int(trainer_id)}" if listed else f"https://t.me/{handle}"


async def _arenas(session: AsyncSession, trainer_id: int) -> list[dict[str, Any]]:
    """Площадки тренера, которые он показывает клиентам; у катка со страницей — ссылка на ``/p/…``."""
    from src.application.indexnow import SITEMAP_PLACE_WHERE_SQL
    from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

    rows = (
        (
            await session.execute(
                text(
                    f"""
                SELECT a.id, a.name, a.city_id, c.name AS city_name, COALESCE(a.venue_type, 'ice') AS venue_type,
                       CASE WHEN {SITEMAP_PLACE_WHERE_SQL} THEN p.slug END AS slug
                FROM trainer_arenas ta
                JOIN arenas a ON a.id = ta.arena_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                LEFT JOIN cities c ON c.id = a.city_id
                WHERE ta.trainer_id = :tid AND COALESCE(ta.is_public, true) AND a.merged_into_arena_id IS NULL
                  AND {PUBLIC_ARENA_VISIBLE_SQL}
                ORDER BY a.sort_order NULLS LAST, a.id
                """
                ),
                {"tid": int(trainer_id), **public_scope_params()},
            )
        )
        .mappings()
        .all()
    )
    return [
        {
            "id": int(r["id"]),
            "name": str(r["name"] or "").strip(),
            "city_id": int(r["city_id"]) if r["city_id"] is not None else None,
            "city_name": str(r["city_name"] or "").strip(),
            "is_ice": str(r["venue_type"]) == "ice",
            "slug": r["slug"],
        }
        for r in rows
        if str(r["name"] or "").strip()
    ]


async def _catalog_city(session: AsyncSession, trainer_id: int, profile_city_id: Any) -> dict[str, Any] | None:
    """Город каталога тренера (``trainer_cities`` — по нему его находит ``/c/{city}/trenery``).

    Городов несколько — тот, где его катки; нет ни одного — город из анкеты.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT c.id, c.name FROM trainer_cities tc JOIN cities c ON c.id = tc.city_id
                WHERE tc.trainer_id = :tid
                ORDER BY EXISTS (
                    SELECT 1 FROM trainer_arenas ta JOIN arenas a ON a.id = ta.arena_id
                    WHERE ta.trainer_id = :tid AND a.city_id = c.id AND COALESCE(ta.is_public, true)
                ) DESC, c.id
                LIMIT 1
                """
            ),
            {"tid": int(trainer_id)},
        )
    ).first()
    if row is None and profile_city_id:
        row = (
            await session.execute(text("SELECT id, name FROM cities WHERE id = :id"), {"id": int(profile_city_id)})
        ).first()
    if row is None or not row[1]:
        return None
    return {"id": int(row[0]), "name": str(row[1])}


async def _glide_since(session: AsyncSession, trainer_id: int) -> date | None:
    """Месяц первой состоявшейся записи (``completed``), без песочницы и записи тренера к себе."""
    from src.application.trainer_client_invite_tracking import sql_booking_not_self

    first = (
        await session.execute(
            text(
                f"""
                SELECT MIN(s.slot_date) FROM bookings b JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid AND b.status = 'completed' AND NOT COALESCE(b.is_sandbox, false)
                  AND {sql_booking_not_self(trainer_id_expr=":tid")}
                """
            ),
            {"tid": int(trainer_id)},
        )
    ).scalar()
    return first if isinstance(first, date) else None


async def _rentals(session: AsyncSession, arena_ids: Sequence[int]) -> dict[int, int]:
    """Прокат коньков по катку — минимум ближайших сеансов, как «Прокат» на странице катка."""
    if not arena_ids:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT arena_id, MIN(price_rental_minor)
            FROM ice_sessions
            WHERE arena_id = ANY(:ids) AND status = 'active' AND price_rental_minor > 0
              AND ends_at_utc > NOW() AND starts_at_utc < NOW() + INTERVAL '14 days'
            GROUP BY arena_id
            """
        ),
        {"ids": list(arena_ids)},
    )
    return {int(a): int(m) for a, m in rows.fetchall() if m is not None}


async def _arena_peer_counts(session: AsyncSession, trainer_id: int, arena_ids: Sequence[int]) -> dict[int, int]:
    """«Здесь же ещё N тренеров»: другие тренеры каталога на катке."""
    if not arena_ids:
        return {}
    rows = await session.execute(
        text(
            f"""
            SELECT ta.arena_id, COUNT(DISTINCT t.id)
            FROM trainer_arenas ta JOIN trainers t ON t.id = ta.trainer_id
            WHERE ta.arena_id = ANY(:ids) AND COALESCE(ta.is_public, true) AND t.id <> :tid
              AND t.status::text <> 'deactivated' AND {CATALOG_LISTED_SQL}
            GROUP BY ta.arena_id
            """
        ),
        {"ids": list(arena_ids), "tid": int(trainer_id)},
    )
    return {int(a): int(n) for a, n in rows.fetchall()}


async def _peers(session: AsyncSession, trainer_id: int, city_id: int, direction: Direction) -> list[dict[str, Any]]:
    """Другие тренеры направления в городе — по правилу каталога: услуга направления и (цена или каток)."""
    from src.application.trainer_use_cases import list_active_trainers_for_client
    from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params
    from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

    items, _total = await list_active_trainers_for_client(session, limit=50, offset=0, city_id=int(city_id))
    bodies = [sanitize_trainer_for_public_catalog(raw) for raw in items if int(raw["id"]) != int(trainer_id)]
    if not bodies:
        return []
    await load_service_directions(session, [s for b in bodies for s in b.get("services") or []])
    ids = [int(b["id"]) for b in bodies]
    rows = await session.execute(
        text(
            f"""
            SELECT ta.trainer_id, a.name FROM trainer_arenas ta JOIN arenas a ON a.id = ta.arena_id
            JOIN cities c ON c.id = a.city_id
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE ta.trainer_id = ANY(:ids) AND COALESCE(ta.is_public, true) AND a.city_id = :city
              AND a.merged_into_arena_id IS NULL AND COALESCE(a.venue_type, 'ice') = 'ice'
              AND {PUBLIC_ARENA_VISIBLE_SQL}
            ORDER BY ta.trainer_id, a.sort_order NULLS LAST, a.id
            """
        ),
        {"ids": ids, "city": int(city_id), **public_scope_params()},
    )
    arenas: dict[int, list[str]] = {}
    for tid, name in rows.fetchall():
        if str(name or "").strip():
            arenas.setdefault(int(tid), []).append(str(name).strip())
    out: list[dict[str, Any]] = []
    for body in bodies:
        svcs = [s for s in body.get("services") or [] if service_direction(s) == direction.key]
        if not svcs:
            continue
        tid = int(body["id"])
        cents = sorted({c for s in svcs for c in ([*_tier_cents(s).values()] or [_min_cents(s) or 0]) if c > 0})
        cur = str(svcs[0].get("currency_code") or "BYN")
        where = arenas.get(tid, [])
        if not cents and not where:
            continue
        name = trainer_name(body)
        out.append(
            {
                "name": name,
                "initial": trainer_initial(name),
                "photo_url": trainer_photo_url(body),
                "path": trainer_path(tid, name),
                "price": (("" if len(cents) == 1 else "от\u00a0") + _money(cents[0], cur))
                if cents
                else "цену уточните",
                "where": (
                    where[0] if len(where) == 1 else f"{len(where)} {plural_ru(len(where), 'каток', 'катка', 'катков')}"
                )
                if where
                else "",
            }
        )
        if len(out) >= PEERS_SHOWN:
            break
    return out


async def load_trainer_page(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Всё для ``/t/…`` или ``None`` (нет такого тренера или он деактивирован)."""
    from src.application.arena_media import attach_arena_media_payloads
    from src.application.arena_public_use_cases import _trainer_windows_on_arena
    from src.application.style_b import b_photo_url, media_url
    from src.application.subscription_tier_use_cases import get_trainer_booking_availability
    from src.application.trainer_min_price import enrich_min_session_price
    from src.application.trainer_use_cases import get_trainer
    from src.shared.notification_hours import NOTIFICATION_TZ
    from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

    raw = await get_trainer(session, int(trainer_id))
    if not raw or str(raw.get("status") or "").strip().lower() == "deactivated":
        return None
    listed = trainer_is_listed(raw)
    username = (
        await session.execute(text("SELECT telegram_username FROM trainers WHERE id = :id"), {"id": int(trainer_id)})
    ).scalar()
    body = sanitize_trainer_for_public_catalog(raw)
    await enrich_min_session_price(session, [body])
    services = [dict(s) for s in body.get("services") or []]
    await load_service_directions(session, services)
    directions, other = group_services(services)
    availability = await get_trainer_booking_availability(session, int(trainer_id))
    can_book = bool(availability.get("can_book"))
    profile = body.get("profile") or {}
    tz = ZoneInfo(NOTIFICATION_TZ)
    today = datetime.now(tz).date()
    windows: list[dict[str, Any]] = []
    if can_book:
        windows = (
            await _trainer_windows_on_arena(
                session,
                None,
                [int(trainer_id)],
                timezone_name=NOTIFICATION_TZ,
                limit=WEEK_WINDOWS_LIMIT,
                days=WEEK_LOOKAHEAD_DAYS,
            )
        ).get(int(trainer_id), [])
        # Неделя — от первого дня с окнами (как сетка в ``_week_html``), а не от сегодня: иначе её последний день пуст.
        if windows:
            first = min(datetime.fromisoformat(w["starts_at"]).date() for w in windows)
            windows = [w for w in windows if (datetime.fromisoformat(w["starts_at"]).date() - first).days < WEEK_DAYS]
    name = trainer_name(body)
    arenas = await _arenas(session, int(trainer_id))
    await attach_arena_media_payloads(session, arenas)
    rentals = await _rentals(session, [a["id"] for a in arenas])
    peer_counts = await _arena_peer_counts(session, int(trainer_id), [a["id"] for a in arenas])
    for a in arenas:
        a["photo_url"] = media_url(a.pop("hero", None), size="card")
        a.pop("gallery", None)
        a["rental_minor"] = rentals.get(a["id"])
        a["peers"] = peer_counts.get(a["id"], 0)
    city = await _catalog_city(session, int(trainer_id), profile.get("city_id"))
    primary = direction_by_key(directions[0]["key"]) if directions else None
    peers = await _peers(session, int(trainer_id), city["id"], primary) if city and primary and listed else []
    photos = body.get("photos") or []
    big_photo = b_photo_url((photos[0] or {}).get("file_key")) if photos else None
    first_name = str(profile.get("first_name") or "").strip()
    from src.shared.phone_guard import sanitize_public_phone

    return {
        "id": int(trainer_id),
        "name": name,
        "first_name": first_name if any(ch.isalpha() for ch in first_name) else "",
        "initial": trainer_initial(name),
        "photo_url": big_photo or trainer_photo_url(body),
        "line": trainer_line(body),
        "listed": listed,
        "can_book": can_book,
        "contact_url": contact_url(int(trainer_id), username, listed=listed),
        "phone": sanitize_public_phone(profile.get("phone")),
        "city": city,
        "city_name": city["name"] if city else "",
        "experience_years": profile.get("experience_years"),
        "description": str(profile.get("description") or "").strip(),
        "education": education_line(profile.get("education")),
        "rating_avg": profile.get("rating_avg"),
        "rating_count": int(profile.get("rating_count") or 0),
        "glide_since": await _glide_since(session, int(trainer_id)),
        "directions": directions,
        "other_services": other,
        "audience": _audience([s for d in directions for s in d["raw"]]),
        "services": [
            {"name": str(s.get("service_name") or "").strip()}
            for s in services
            if str(s.get("service_name") or "").strip()
        ],
        "arenas": arenas,
        "peers": peers,
        "today": today,
        "windows": windows,
        "path": trainer_path(int(trainer_id), name),
    }


async def sitemap_rows(session: AsyncSession) -> list[str]:
    """Пути ``/t/…`` всех, кто в каталоге — тот же предикат, что у списка тренеров в Mini App."""
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.id, COALESCE(p.first_name, ''), COALESCE(p.last_name, '')
                FROM trainers t LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
                WHERE {CATALOG_LISTED_SQL}
                ORDER BY t.id
                """
            )
        )
    ).all()
    out = []
    for tid, first, last in rows:
        name = f"{str(first).strip()} {str(last).strip()}".strip() or "Тренер"
        out.append(trainer_path(int(tid), name))
    return out


# ── Ссылка, которой тренер делится ───────────────────────────────────

#: Метка ссылки из кабинета: человек пришёл от самого тренера — кнопка ведёт через ``welcome_ref``.
SHARE_VIA = "link"
#: Метка «Поделиться тренером» из Mini App: клиент советует другу — кнопка ведёт через ``share_ref``.
RECOMMEND_VIA = "share"


def share_url(base_url: str, trainer_id: int, name: str, *, via: str = SHARE_VIA) -> str | None:
    """``https://glideclub.by/t/9-aleksandr-gaevskiy?via=link`` — только на настоящем https-адресе сайта."""
    base = (base_url or "").strip().rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return f"{trainer_page_url(base, trainer_id, name)}?via={via}"


async def trainer_invite_link(session: AsyncSession, trainer_id: int) -> tuple[str | None, str | None]:
    """Ссылка тренера ученикам — страница сайта ``/t/…`` (TASK-350), а не ``t.me``.

    Контракт ``build_trainer_universal_invite_link``: ``(ссылка, ошибка)``. Без https-адреса сайта
    (локально) — прежняя ``t.me/…?start=welcome_ref_{id}``. Кнопка на странице по ``via=link`` ведёт
    туда же, через ``welcome_ref``: бот привязывает и регистрирует ученика, как раньше.
    """
    from src.application.trainer_invite_links import build_trainer_universal_invite_link
    from src.shared.config import Settings

    settings = Settings()  # type: ignore[call-arg]
    fallback, err = build_trainer_universal_invite_link(
        client_bot_username=settings.client_bot_username, trainer_id=int(trainer_id)
    )
    if err:
        return None, err
    return await site_share_link(session, int(trainer_id), via=SHARE_VIA) or fallback, None


async def site_share_link(session: AsyncSession, trainer_id: int, *, via: str) -> str | None:
    """Канонический ``/t/…?via=…`` по имени из профиля (не по подписи вроде «Анна К.» — без лишнего 301)."""
    from src.shared.config import Settings

    row = (
        await session.execute(
            text("SELECT first_name, last_name FROM trainer_profiles WHERE trainer_id = :id"), {"id": int(trainer_id)}
        )
    ).first()
    name = " ".join(str(v or "").strip() for v in (row or ())).strip()
    return share_url(Settings().webapp_base_url or "", int(trainer_id), name, via=via)  # type: ignore[call-arg]


# ── Ссылки в Telegram ────────────────────────────────────────────────


def app_url(
    base_url: str, page: Mapping[str, Any], *, client_bot_username: str | None, via: str | None = None
) -> str | None:
    """Куда ведёт «Записаться в Telegram»: карточка тренера в Mini App.

    В каталоге — через учётный ``/api/public/catalog/open-telegram`` (``trainer_{id}``). Пришли по
    ссылке самого тренера (``via=link``) или тренера нет в каталоге — постоянная ссылка
    ``welcome_ref_{id}``: бот привяжет человека к тренеру, как раньше по ссылке из кабинета
    (карточка Mini App незнакомому клиенту скрытого тренера отвечает 404).
    """
    if via == RECOMMEND_VIA:
        from src.application.trainer_invite_links import build_trainer_share_link

        rec, _err = build_trainer_share_link(
            webapp_base_url=base_url, client_bot_username=client_bot_username, trainer_id=int(page["id"])
        )
        if rec is not None:
            return rec.bot_deep_link
    if page["listed"] and via != SHARE_VIA:
        from src.application.booking_source import clean_place_via

        # Метка места (``?via=p3``) едет в ``startapp`` — источник записи (TASK-351).
        return public_telegram_cta_url(
            base_url,
            start_param=trainer_start_param(int(page["id"]), via=clean_place_via(via)),
            surface=TRAINER_SURFACE,
        )
    from src.application.trainer_invite_links import build_trainer_universal_invite_link

    link, _err = build_trainer_universal_invite_link(
        client_bot_username=client_bot_username, trainer_id=int(page["id"])
    )
    return link


def slot_app_url(
    base_url: str,
    page: Mapping[str, Any],
    slot_id: int | None,
    *,
    client_bot_username: str | None,
    via: str | None = None,
) -> str | None:
    """Время на странице — сразу запись на этот слот (``trainer_<id>_s_<slot>``, TASK-357).

    По ссылке тренера/рекомендации (``via=link``/``share``) вход через бота: слот едет в его
    ``start`` — ``welcome_ref_<id>_s_<slot>`` / ``share_ref_<id>_s_<slot>``; бот привяжет клиента
    к тренеру, как раньше, и откроет витрину сразу на этом времени. Только для тренера в каталоге
    (карточка Mini App незнакомому клиенту скрытого тренера отвечает 404) — иначе время ведёт туда
    же, куда «Записаться».
    """
    if slot_id and page["listed"] and via in (SHARE_VIA, RECOMMEND_VIA):
        from src.application.trainer_invite_links import build_trainer_share_link, build_trainer_universal_invite_link

        if via == RECOMMEND_VIA:
            rec, _err = build_trainer_share_link(
                webapp_base_url=base_url,
                client_bot_username=client_bot_username,
                trainer_id=int(page["id"]),
                slot_id=int(slot_id),
            )
            if rec is not None:
                return rec.bot_deep_link
        else:
            link, _err = build_trainer_universal_invite_link(
                client_bot_username=client_bot_username, trainer_id=int(page["id"]), slot_id=int(slot_id)
            )
            if link:
                return link
    if slot_id and page["listed"] and via not in (SHARE_VIA, RECOMMEND_VIA):
        from src.application.booking_source import clean_place_via

        return public_telegram_cta_url(
            base_url,
            start_param=trainer_start_param(int(page["id"]), slot_id=int(slot_id), via=clean_place_via(via)),
            surface=TRAINER_SURFACE,
        )
    return app_url(base_url, page, client_bot_username=client_bot_username, via=via)


def primary_cta(
    base_url: str, page: Mapping[str, Any], *, client_bot_username: str | None, via: str | None = None
) -> tuple[str, str] | None:
    """(подпись, адрес) главной кнопки. Подпись не обещает того, чего нет: без подписки — «Написать»."""
    app = app_url(base_url, page, client_bot_username=client_bot_username, via=via)
    if page["can_book"] and app:
        return "Записаться в Telegram", app
    if page.get("contact_url"):
        return "Написать в Telegram", str(page["contact_url"])
    if app:
        return "Открыть в Telegram", app
    return None


# ── SEO ──────────────────────────────────────────────────────────────


def page_title(page: Mapping[str, Any]) -> str:
    name = str(page["name"])
    city = str(page.get("city_name") or "")
    first_service = (page.get("services") or [{}])[0].get("name") if page.get("services") else ""
    candidates = [
        f"{name} — тренер{', ' + city if city else ''} · Glideclub",
        f"{name} — тренер · Glideclub",
        name,
    ]
    if first_service:
        candidates.insert(0, f"{name} — {first_service}{', ' + city if city else ''} · Glideclub")
    for c in candidates:
        if len(c) <= TITLE_LIMIT:
            return c
    return candidates[-1][:TITLE_LIMIT]


def page_description(page: Mapping[str, Any]) -> str:
    bits = [str(page["name"]), "тренер"]
    arenas = [a["name"] for a in page.get("arenas") or []]
    if arenas:
        bits.append("занимается: " + ", ".join(arenas[:3]))
    line = str(page.get("line") or "")
    if line:
        bits.append(line.replace(" ", " "))
    tail = "Запись в Telegram, ничего не устанавливая." if page.get("can_book") else "Написать тренеру в Telegram."
    text_ = ". ".join([" — ".join(bits[:2])] + bits[2:]) + ". " + tail
    return text_ if len(text_) <= DESCRIPTION_LIMIT else text_[: DESCRIPTION_LIMIT - 1].rstrip() + "…"


def jsonld(page: Mapping[str, Any], *, canonical: str, base_url: str) -> str:
    person: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": page["name"],
        "url": canonical,
        "jobTitle": "Тренер по катанию",
    }
    if page.get("photo_url"):
        person["image"] = _absolute(base_url, str(page["photo_url"]))
    if page.get("description"):
        person["description"] = str(page["description"])[:300]
    if page.get("city_name"):
        person["address"] = {"@type": "PostalAddress", "addressLocality": page["city_name"]}
    places = [
        {
            "@type": "SportsActivityLocation",
            "name": a["name"],
            "url": place_page_url(base_url=base_url, city_name=a["city_name"], slug=a["slug"]),
        }
        for a in page.get("arenas") or []
        if a.get("slug") and a.get("city_name")
    ]
    if places:
        person["workLocation"] = places
    payload = json.dumps(person, ensure_ascii=False).replace("</", "<\\/")
    # Тег <script> уже в шаблоне b.html — здесь только JSON (раньше выходил тег в теге).
    return payload


def _absolute(base_url: str, url: str) -> str:
    return url if url.startswith("http") else f"{(base_url or '').rstrip('/')}{url}"


def write_beacon_url(page: Mapping[str, Any], *, via: str | None = None) -> str:
    """Учёт «Написать в Telegram» (TASK-351): тренер и место, откуда пришли на страницу.

    Маяк, а не редирект: у тренера вне каталога ``/r/tg`` нет, ссылка ведёт прямо в ``t.me``.
    """
    from src.application.booking_source import clean_place_via, source_from_via
    from src.application.public_web_cta import CONTACT_ACTION_TELEGRAM, contact_click_beacon_url

    src = source_from_via(via)
    return contact_click_beacon_url(
        action=CONTACT_ACTION_TELEGRAM,
        surface=TRAINER_SURFACE,
        arena_id=src.arena_id if src else None,
        city_id=src.city_id if src else None,
        trainer_id=int(page["id"]),
        via=clean_place_via(via) or (src.code if src else None),
    )


# ── Вёрстка ──────────────────────────────────────────────────────────


def _rating_ok(page: Mapping[str, Any]) -> bool:
    return bool(page.get("rating_avg")) and int(page.get("rating_count") or 0) >= RATING_MIN_COUNT


def _n_ratings(n: int) -> str:
    return f"{n} {plural_ru(n, 'оценка', 'оценки', 'оценок')}"


def _avg(page: Mapping[str, Any]) -> str:
    return f"{float(page['rating_avg']):.1f}".replace(".", ",")


def _years(page: Mapping[str, Any]) -> int:
    try:
        return max(0, int(page.get("experience_years") or 0))
    except (TypeError, ValueError):
        return 0


def _since_text(page: Mapping[str, Any]) -> str:
    since = page.get("glide_since")
    return f"В Glide с {_MONTHS_GEN[since.month - 1]} {since.year}" if isinstance(since, date) else ""


def _arenas_check(page: Mapping[str, Any]) -> str:
    """Галочка «Каток: …» — ледовые катки из анкеты (лыжероллерная трасса — не каток)."""
    names = [str(a["name"]) for a in page.get("arenas") or [] if a.get("is_ice")]
    if not names:
        return ""
    if len(names) > 2:
        rest = len(names) - 2
        return f"Каток: {names[0]}, {names[1]} и ещё {rest} {plural_ru(rest, 'каток', 'катка', 'катков')}"
    return "Каток: " + ", ".join(names)


def _win_label(w: Mapping[str, Any]) -> str:
    """«сб, 17:15» — день недели всегда, и сегодня тоже: подпись «сегодня» — строкой ниже."""
    starts = datetime.fromisoformat(str(w["starts_at"]))
    return f"{_WEEKDAYS[starts.weekday()]}, {w['time']}"


def _near_label(w: Mapping[str, Any], today: date) -> tuple[str, str]:
    """(«сб, 17:15», «сегодня» / «завтра» / «10 ноября»)."""
    return _win_label(w), human_date(datetime.fromisoformat(str(w["starts_at"])).date(), today=today)


def _write_attrs(page: Mapping[str, Any], via: str | None) -> str:
    return f' rel="nofollow" data-catalog-phone-beacon="{esc(write_beacon_url(page, via=via))}"'


def _tiers_html(prices: Sequence[tuple[str, str]]) -> str:
    if not prices:
        return '<p class="tp-noprice">Цену уточните у тренера</p>'
    return (
        '<div class="tp-tiers">'
        + "".join(f"<div><span>{esc(label)}</span><b>{esc(val)}</b></div>" for label, val in prices)
        + "</div>"
    )


_SVC_HOOK_MAX = 110


def _hook_short(text: str) -> str:
    """Крючок в блоке услуги (их несколько): режем по границе слова, не посреди слова."""
    t = " ".join(str(text).split())
    if len(t) <= _SVC_HOOK_MAX:
        return t
    return t[:_SVC_HOOK_MAX].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"


def _prices_line(prices: Sequence[tuple[str, str]]) -> str:
    """Цены услуги одной строкой: «Ребёнок 50 BYN · Взрослый 55 BYN» / «Дети и взрослые 50 BYN»."""
    if not prices:
        return '<p class="tp-noprice">Цену уточните у тренера</p>'
    return '<p class="tp-prices">' + " · ".join(f"{esc(label)} <b>{esc(val)}</b>" for label, val in prices) + "</p>"


def _panel_html(services: Sequence[Mapping[str, Any]]) -> str:
    """Цена направления в карточке. Услуга одна — крупные цены; несколько — блок на услугу с ценами в одну строку."""

    def hook(s: Mapping[str, Any], text: str) -> str:
        return f'<p class="tp-hook">{esc(text)}</p>' if text else ""

    if len(services) == 1 and not services[0].get("own"):
        return hook(services[0], services[0].get("hook") or "") + _tiers_html(services[0]["card_prices"])
    return "".join(
        f'<div class="tp-svc"><span class="tp-svc__name">{esc(s["title"])}</span>'
        f"{hook(s, _hook_short(s['hook']) if s.get('hook') else '')}{_prices_line(s['card_prices'])}</div>"
        for s in services
    )


def _also_line(page: Mapping[str, Any]) -> str:
    names = [s["title"] for s in page.get("other_services") or [] if s.get("name")]
    return f'<p class="tp-also">Ещё ведёт: {esc(", ".join(names))}.</p>' if names else ""


def _phone_act(page: Mapping[str, Any]) -> str:
    """Кнопка «Скопировать телефон», если в анкете есть публичный номер."""
    phone = page.get("phone")
    if not phone:
        return ""
    return (
        f'<div class="tp-act"><button type="button" class="tp-btn tp-btn--ghost" data-copy="{esc(phone)}">'
        f"Скопировать телефон</button></div>"
    )


def _price_card(page: Mapping[str, Any], *, app: str | None, cta: tuple[str, str] | None, via: str | None) -> str:
    dirs = page.get("directions") or []
    panels = [(d["key"], d["tab"], d["services"]) for d in dirs]
    also = _also_line(page)
    if not panels and page.get("other_services"):
        # Своих вкладок нет (только ролики, ОФП, своя услуга) — карточка показывает их цены.
        panels = [("other", "", page["other_services"])]
        also = ""
    parts: list[str] = []
    if len(panels) > 1:
        parts.append(
            '<div class="tp-dsw" role="group" aria-label="Занятие">'
            + "".join(
                f'<button type="button" data-dir="{esc(k)}" aria-pressed="{"true" if i == 0 else "false"}">{esc(tab)}</button>'
                for i, (k, tab, _s) in enumerate(panels)
            )
            + "</div>"
        )
    for i, (k, _tab, svcs) in enumerate(panels):
        parts.append(
            f'<div class="tp-panel" data-dir-panel="{esc(k)}"{"" if i == 0 else " hidden"}>{_panel_html(svcs)}</div>'
        )
    if not panels:
        parts.append(_tiers_html([]))
    wins = page.get("windows") or []
    contact = page.get("contact_url")
    if page.get("can_book") and app:
        if wins:
            today = page["today"]
            near = []
            for w in wins[:NEAR_SHOWN]:
                label, sub = _near_label(w, today)
                near.append(
                    f'<a href="{esc(w.get("book_href") or app)}" rel="nofollow" aria-label="Записаться: {esc(label)}, {esc(sub)}">'
                    f"{esc(label)}<small>{esc(sub)}</small></a>"
                )
            parts.append(
                '<div><div class="tp-lbl">Ближайшее время — записаться</div>'
                f'<div class="tp-near">{"".join(near)}</div></div>'
            )
            # Одна главная кнопка — та же, что внизу Mini App: ближайшее время, без выбора.
            parts.append(
                f'<div class="tp-act"><a class="tp-btn tp-btn--teal" href="{esc(wins[0].get("book_href") or app)}" rel="nofollow">'
                f"Записаться на {esc(_win_label(wins[0]))}</a></div>"
            )
        else:
            # Текст не обещает «напишите», если ника нет и кнопки «Написать» не будет.
            nowin = (
                "Индивидуального свободного времени на этой неделе нет — напишите тренеру."
                if contact
                else "Индивидуального свободного времени на этой неделе нет — следующие недели видны в Telegram."
            )
            parts.append(
                f'<p class="tp-nowin">{esc(nowin)}</p>'
                f'<div class="tp-act"><a class="tp-btn tp-btn--teal" href="{esc(app)}" rel="nofollow">Следующие недели — в Telegram</a></div>'
            )
        if contact:
            parts.append(
                f'<div class="tp-act"><a class="tp-btn tp-btn--ghost" href="{esc(contact)}"{_write_attrs(page, via)}>Написать тренеру</a></div>'
            )
        parts.append(_phone_act(page))
        parts.append(also)
        parts.append(
            '<span class="tp-fine">Нужен Telegram — запись и переписка идут там. Оплата тренеру на месте.</span>'
        )
    else:
        if cta:
            label, href = cta
            attrs = _write_attrs(page, via) if href == contact else ' rel="nofollow"'
            parts.append(
                f'<div class="tp-act"><a class="tp-btn tp-btn--tg" href="{esc(href)}"{attrs}>{esc(label)}</a></div>'
            )
        parts.append(_phone_act(page))
        parts.append(also)
        if contact:
            fine = "Онлайн-записи нет — напишите и договоритесь о времени. Нужен Telegram — переписка идёт там."
        elif page.get("phone"):
            fine = "Онлайн-записи нет — позвоните или откройте Telegram и договоритесь о времени."
        else:
            fine = "Онлайн-записи нет — откройте Telegram и договоритесь о времени."
        parts.append(f'<span class="tp-fine">{esc(fine)}</span>')
    return f'<div class="tp-pcard" id="tp-pcard">{"".join(p for p in parts if p)}</div>'


def _hero(page: Mapping[str, Any], card: str, *, compact: bool) -> str:
    photo = page.get("photo_url")
    if photo and not compact:
        media = f'<div class="tp-photo"><img src="{esc(photo)}" alt="{esc(page["name"])}" decoding="async" fetchpriority="high" /></div>'
    elif photo:
        media = f'<img class="tp-ava" src="{esc(photo)}" alt="" width="72" height="72" decoding="async" />'
    else:
        media = f'<span class="tp-ava tp-ava--mono" aria-hidden="true">{esc(page["initial"])}</span>'
    years = _years(page)
    badge = f'<span class="tp-badge">Тренирует {years} {plural_ru(years, "год", "года", "лет")}</span>' if years else ""
    head = f'{badge}<h1 class="tp-name">{esc(page["name"])}</h1>'
    if not compact:
        dirs = [direction_by_key(d["key"]) for d in page.get("directions") or []]
        role = " ".join(x for x in (_role_line(dirs), str(page.get("audience") or "")) if x)
        if role:
            head += f'<p class="tp-role">{esc(role)}</p>'
        bio = tidy_text(page.get("description"))
        if bio:
            head += f'<p class="tp-bio">{esc(bio)}</p>'
        if _rating_ok(page):
            head += (
                f'<p class="tp-rate"><i aria-hidden="true">★</i>{esc(_avg(page))} '
                f"<span>· {esc(_n_ratings(int(page['rating_count'])))}</span></p>"
            )
        since = _since_text(page)
        if since:
            head += f'<p class="tp-since">{esc(since)}</p>'
        checks = [c for c in (page.get("education"), _arenas_check(page)) if c]
        if checks:
            head += '<ul class="tp-checks">' + "".join(f"<li>{esc(c)}</li>" for c in checks) + "</ul>"
    if photo and not compact:
        top = media + f'<div class="tp-head">{head}</div>'
    else:
        top = f'<div class="tp-top">{media}<div class="tp-head">{head}</div></div>'
    return f'<section class="tp-th">{top}{card}</section>'


def _sec(title: str, body: str, *, sec_id: str = "", nosnippet: bool = False) -> str:
    if not body:
        return ""
    id_attr = f' id="{esc(sec_id)}"' if sec_id else ""
    snip = " data-nosnippet" if nosnippet else ""
    return f'<section class="tp-sec"{id_attr}{snip}><h2 class="b-h2 tp-h2">{esc(title)}</h2>{body}</section>'


_ARROW_PREV = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
_ARROW_NEXT = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def _scroller(strip: str) -> str:
    """Горизонтальная лента со стрелками «листать»: стрелки показывает ``_SCROLLER_SCRIPT``, только когда есть куда."""
    return (
        f'<div class="tp-scroller" data-scroller>{strip}'
        f'<button type="button" class="tp-arrow tp-arrow--prev" aria-label="Назад" tabindex="-1">{_ARROW_PREV}</button>'
        f'<button type="button" class="tp-arrow tp-arrow--next" aria-label="Дальше" tabindex="-1">{_ARROW_NEXT}</button>'
        "</div>"
    )


def _week_html(page: Mapping[str, Any], app: str | None, via: str | None) -> str:
    wins = page.get("windows") or []
    if not (page.get("can_book") and app and wins):
        return ""
    today: date = page["today"]
    by_day: dict[date, list[Mapping[str, Any]]] = {}
    for w in wins:
        by_day.setdefault(datetime.fromisoformat(str(w["starts_at"])).date(), []).append(w)
    # Неделя начинается с первого дня, где есть время: «сегодня — нет окон» первым экраном не показываем.
    start = min((d for d in by_day if d >= today), default=today)
    cells = []
    for i in range(WEEK_DAYS):
        day = start + timedelta(days=i)
        slots = by_day.get(day, [])
        inner = (
            "".join(
                f'<a class="tp-slot" href="{esc(w.get("book_href") or app)}" rel="nofollow" '
                f'aria-label="Записаться: {esc(_WEEKDAYS[day.weekday()])}, {day.day}, {esc(w["time"])}">{esc(w["time"])}</a>'
                for w in slots
            )
            if slots
            else '<span class="tp-no">нет окон</span>'
        )
        cells.append(
            f'<div class="tp-day{" tp-day--today" if day == today else ""}{"" if slots else " tp-day--empty"}">'
            f'<b>{esc(_WEEKDAYS[day.weekday()])}</b><span class="tp-d">{day.day}</span>{inner}</div>'
        )
    body = f'<div class="tp-week">{"".join(cells)}</div>'
    if page.get("contact_url"):
        body += (
            '<div class="tp-request"><div><b>Не подходит время?</b>'
            "<span>Напишите тренеру — он предложит своё.</span></div>"
            f'<a class="tp-btn tp-btn--ghost" href="{esc(page["contact_url"])}"{_write_attrs(page, via)}>Написать</a></div>'
        )
    return _sec("Всё время на неделю", body, sec_id="time", nosnippet=True)


def _prices_html(page: Mapping[str, Any]) -> str:
    cards = []
    groups = [(d["tab"], d["services"]) for d in page.get("directions") or []]
    groups += [(s["title"], [s]) for s in page.get("other_services") or [] if s.get("prices")]
    if not any(s.get("prices") for _t, svcs in groups for s in svcs):
        return ""
    for title, svcs in groups:
        inner = ""
        for s in svcs:
            if len(svcs) > 1 or s.get("own"):
                inner += f'<h4 class="tp-svc__name">{esc(s["title"])}</h4>'
            if s.get("hook"):
                inner += f'<p class="tp-lead">{esc(s["hook"])}</p>'
            if s.get("body"):
                inner += f'<p class="tp-words">{esc(s["body"])}</p>'
            if s.get("description"):
                inner += (
                    '<figure class="tp-quote"><figcaption>Слова тренера</figcaption>'
                    f'<blockquote class="tp-words">{esc(s["description"])}</blockquote></figure>'
                )
            if s.get("prices"):
                inner += (
                    "<dl>"
                    + "".join(f"<div><dt>{esc(label)}</dt><dd>{esc(val)}</dd></div>" for label, val in s["prices"])
                    + "</dl>"
                )
            else:
                inner += '<p class="tp-muted">Цену уточните у тренера</p>'
            if s.get("notice"):
                inner += f'<p class="tp-notice"><b>Не входит в цену:</b> {esc(s["notice"])}</p>'
        cards.append(f'<div class="tp-card"><h3>{esc(title)}</h3>{inner}</div>')
    body = (
        f'<div class="tp-plist">{"".join(cards)}</div>'
        '<p class="tp-muted">Цена за одно занятие. Билет на каток покупается отдельно, на кассе.</p>'
    )
    return _sec("Занятия и цены", body)


def tidy_text(value: Any) -> str:
    """Текст тренера как есть, но без «слово ,» и двойных пробелов (как ``tidyText`` в Mini App)."""
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", str(value or ""))
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _about_html(page: Mapping[str, Any], *, ratings: bool) -> str:
    cards = []
    # На полной странице слова тренера — под именем (_hero); отдельная карточка — только в компактной.
    desc = "" if ratings else tidy_text(page.get("description"))
    if desc:
        cards.append(f'<div class="tp-card"><h3>О тренере</h3><p class="tp-words">{esc(desc)}</p></div>')
    if ratings and _rating_ok(page):
        n = int(page["rating_count"])
        avg = float(page["rating_avg"])
        stars = "★" * max(1, min(5, round(avg)))
        what = f"{_n_ratings(n)} — все на 5 из 5" if avg >= 5 else f"{_n_ratings(n)}, в среднем {_avg(page)} из 5"
        cards.append(
            '<div class="tp-card"><h3>Оценки учеников</h3>'
            f'<div class="tp-score"><b>{esc(_avg(page))}</b><div><i aria-hidden="true">{stars}</i><span>{esc(what)}</span></div></div>'
            '<p class="tp-muted">Оценить занятие можно только после того, как оно состоялось.</p></div>'
        )
    return f'<section class="tp-sec"><div class="tp-two">{"".join(cards)}</div></section>' if cards else ""


def _after_html(page: Mapping[str, Any]) -> str:
    if not page.get("can_book"):
        return ""
    who = str(page.get("first_name") or "") or "Тренер"
    steps = (
        ("Откроется Telegram", "Устанавливать ничего не нужно."),
        (f"{who} подтвердит", "Подтверждение придёт сообщением в Telegram."),
        ("Оплата на месте", "Платите при встрече. Билет на каток — на кассе."),
        ("Планы поменялись", "Отмените запись в «Мои записи»."),
    )
    body = (
        '<div class="tp-after">'
        + "".join(f"<div><i>{i}</i><b>{esc(b)}</b><span>{esc(s)}</span></div>" for i, (b, s) in enumerate(steps, 1))
        + "</div>"
    )
    return _sec("Что будет после записи", body)


def _faq_html(page: Mapping[str, Any]) -> str:
    """«Перед первым занятием»: три вопроса главного направления, ответы из данных — или вопроса нет."""
    dirs = page.get("directions") or []
    if not dirs:
        return ""
    d = direction_by_key(dirs[0]["key"])
    rents = [
        (str(a["name"]), _money(int(a["rental_minor"]), "BYN"))
        for a in page.get("arenas") or []
        if a.get("rental_minor")
    ]
    pair = any(s.get("pair") for s in dirs[0]["services"])
    city = page.get("city")
    items: list[tuple[str, str]] = []
    for q, a in d.faq:
        if a is not None:
            ans = esc(a)
        elif q == "Своих коньков нет" and rents:
            ans = esc("Возьмите в прокате: " + ", ".join(f"в {n} — {p}" for n, p in rents[:3]) + ".")
        elif q == "Можно заниматься вместе с ребёнком?" and pair:
            ans = esc("Да, у тренера есть цена «взрослый + ребёнок» — она в ценах выше.")
        elif q == "Где потом поиграть?" and city:
            ans = f'Расписание ОХМ — в разделе «С клюшкой» на <a href="/c/{esc(city_slug(city["name"]))}">странице города</a>.'
        else:
            continue
        items.append((q, ans))
        if len(items) >= 3:
            break
    if not items:
        return ""
    body = (
        '<div class="tp-faq">'
        + "".join(
            f"<details{' open' if i == 0 else ''}><summary>{esc(q)}</summary><p>{a}</p></details>"
            for i, (q, a) in enumerate(items)
        )
        + "</div>"
    )
    if city:
        body += f'<a class="tp-link" href="{esc(catalog_path(city["name"], d))}">Все вопросы о занятиях «{esc(d.tab)}» →</a>'
    return _sec("Перед первым занятием", body)


def _arenas_html(page: Mapping[str, Any], base_url: str) -> str:
    cards = []
    for a in page.get("arenas") or []:
        img = (
            f'<img src="{esc(a["photo_url"])}" alt="" loading="lazy" decoding="async" />' if a.get("photo_url") else ""
        )
        peers = int(a.get("peers") or 0)
        lines = f"<b>{esc(a['name'])}</b>"
        if peers:
            lines += f"<span>Здесь же ещё {peers} {plural_ru(peers, 'тренер', 'тренера', 'тренеров')}</span>"
        rent = f"Прокат — {_money(int(a['rental_minor']), 'BYN')}" if a.get("rental_minor") else ""
        href = (
            place_page_url(base_url=base_url, city_name=a["city_name"], slug=a["slug"])
            if a.get("slug") and a.get("city_name")
            else ""
        )
        tail = " · ".join(x for x in (rent, "расписание ›" if href else "") if x)
        if tail:
            lines += f"<em>{esc(tail)}</em>"
        klass = "tp-ar" + ("" if img else " tp-ar--noimg")
        inner = f"{img}<div>{lines}</div>"
        cards.append(
            f'<a class="{klass}" href="{esc(href)}">{inner}</a>' if href else f'<div class="{klass}">{inner}</div>'
        )
    return _sec("Где занимается", f'<div class="tp-arenas">{"".join(cards)}</div>') if cards else ""


def _in_city(page: Mapping[str, Any]) -> str:
    name = str(page.get("city_name") or "")
    loc = city_locative(name) if name else None
    return f"в {loc}" if loc else ""


def _peers_html(page: Mapping[str, Any]) -> str:
    peers = page.get("peers") or []
    dirs = page.get("directions") or []
    if not peers or not dirs:
        return ""
    d = direction_by_key(dirs[0]["key"])
    minis = []
    for p in peers:
        img = (
            f'<img src="{esc(p["photo_url"])}" alt="" loading="lazy" decoding="async" />'
            if p.get("photo_url")
            else f'<span class="tp-mini__mono" aria-hidden="true">{esc(p["initial"])}</span>'
        )
        sub = " · ".join(x for x in (p.get("price"), p.get("where")) if x)
        minis.append(
            f'<a class="tp-mini" href="{esc(p["path"])}">{img}<div><b>{esc(p["name"])}</b><span>{esc(sub)}</span></div></a>'
        )
    title = " ".join(x for x in (f"Ещё тренеры «{d.tab}»", _in_city(page)) if x)
    return _sec(title, _scroller(f'<div class="tp-more">{"".join(minis)}</div>'))


def _band_html(page: Mapping[str, Any]) -> str:
    """Тренер среди родителей — тоже вход в Glide (trainer-acquisition, канал 3)."""
    where = _in_city(page)
    return (
        f'<div class="tp-band"><div><b>{esc("Тренируете " + where + "?" if where else "Тренируете?")}</b>'
        "<span>Бесплатная страница тренера и ссылка для ваших учеников.</span></div>"
        '<a class="tp-btn tp-btn--tg" href="/trainers?utm_source=glide&amp;utm_medium=trainer_page">Создать страницу</a></div>'
    )


def _mbar_html(page: Mapping[str, Any], app: str | None) -> str:
    """Закреплённая «Записаться на …» на телефоне — пока карточка цены не на экране."""
    wins = page.get("windows") or []
    if not (page.get("can_book") and app and wins):
        return ""
    label = _win_label(wins[0])
    return (
        f'<div class="tp-mbar" id="tp-mbar" hidden><a class="tp-btn tp-btn--teal" href="{esc(wins[0].get("book_href") or app)}" rel="nofollow">'
        f"Записаться на {esc(label)}</a><small>Запись в Telegram · оплата на месте</small></div>"
    )


_PAGE_SCRIPT = (
    "<script>(function(){"
    "var card=document.getElementById('tp-pcard');if(!card)return;"
    "var tabs=card.querySelectorAll('[data-dir]');"
    "function pick(k){for(var i=0;i<tabs.length;i++){tabs[i].setAttribute('aria-pressed',tabs[i].getAttribute('data-dir')===k?'true':'false');}"
    "var ps=card.querySelectorAll('[data-dir-panel]');for(var j=0;j<ps.length;j++){ps[j].hidden=ps[j].getAttribute('data-dir-panel')!==k;}}"
    "for(var i=0;i<tabs.length;i++){tabs[i].addEventListener('click',function(e){pick(e.currentTarget.getAttribute('data-dir'));});}"
    "var bar=document.getElementById('tp-mbar');"
    "if(bar&&typeof IntersectionObserver==='function'){"
    "new IntersectionObserver(function(es){bar.hidden=es[es.length-1].isIntersecting;}).observe(card);}"
    "})();</script>"
)


_SCROLLER_SCRIPT = (
    "<script>(function(){"
    "var ws=document.querySelectorAll('[data-scroller]');"
    "for(var i=0;i<ws.length;i++){(function(w){"
    "var s=w.firstElementChild,p=w.querySelector('.tp-arrow--prev'),n=w.querySelector('.tp-arrow--next');"
    "function upd(){var m=s.scrollWidth-s.clientWidth;"
    "w.classList.toggle('has-prev',s.scrollLeft>4);w.classList.toggle('has-next',m>4&&s.scrollLeft<m-4);}"
    "function go(d){s.scrollBy({left:d*s.clientWidth*0.8,behavior:'smooth'});}"
    "p.addEventListener('click',function(){go(-1);});n.addEventListener('click',function(){go(1);});"
    "s.addEventListener('scroll',upd,{passive:true});window.addEventListener('resize',upd);upd();"
    "})(ws[i]);}"
    "})();</script>"
)


def render_trainer_page(
    page: Mapping[str, Any], *, base_url: str, client_bot_username: str | None, via: str | None = None
) -> str:
    from src.application.catalog_home_page import catalog_home_og_image_url
    from src.application.catalog_list_share import catalog_list_share_tail
    from src.application.place_links import breadcrumb_script
    from src.application.public_analytics import public_analytics_head_html_from_settings
    from src.application.public_site_footer import render_site_footer_html
    from src.application.public_web_cta import phone_beacon_script, public_page_view_beacon_script
    from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION, public_fonts_head_html

    base = (base_url or "").rstrip("/")
    canonical = f"{base}{page['path']}"
    app = app_url(base_url, page, client_bot_username=client_bot_username, via=via)
    if page.get("can_book") and app:
        page = {
            **page,
            "windows": [
                {
                    **w,
                    "book_href": slot_app_url(
                        base_url, page, w.get("slot_id"), client_bot_username=client_bot_username, via=via
                    ),
                }
                for w in page.get("windows") or []
            ],
        }
    cta = primary_cta(base_url, page, client_bot_username=client_bot_username, via=via)
    # Пришли по ссылке самого тренера (свои ученики): время сверху, без продающих блоков.
    own = via == SHARE_VIA
    city = page.get("city")
    crumbs_html = ""
    if city:
        crumbs_html = (
            '<nav class="tp-crumbs" aria-label="Навигация">'
            f'<a href="/c/{esc(city_slug(city["name"]))}">{esc(city["name"])}</a> › '
            f'<a href="{esc(catalog_path(city["name"]))}">Тренеры</a> › <span>{esc(page["name"])}</span></nav>'
        )
    card = _price_card(page, app=app, cta=cta, via=via)
    body = (
        '<div class="tp">'
        '<div class="tp-bar"><a class="b-brand" href="/">Glide</a></div>'
        + crumbs_html
        + _hero(page, card, compact=own)
        + _week_html(page, app, via)
        + _prices_html(page)
        + _about_html(page, ratings=not own)
        + _after_html(page)
        + _faq_html(page)
        + _arenas_html(page, base_url)
        + ("" if own else _peers_html(page) + _band_html(page))
        + "</div>"
        + _mbar_html(page, app)
        + _PAGE_SCRIPT
        + _SCROLLER_SCRIPT
    )
    crumbs = [("Glideclub", f"{base}/")]
    if city:
        crumbs.append((str(city["name"]), f"{base}/c/{city_slug(str(city['name']))}"))
        crumbs.append(("Тренеры", f"{base}{catalog_path(str(city['name']))}"))
    crumbs.append((str(page["name"]), canonical))
    body += breadcrumb_script(canonical, crumbs)
    body += phone_beacon_script(body)
    og_image = (
        _absolute(base_url, str(page["photo_url"])) if page.get("photo_url") else catalog_home_og_image_url(base_url)
    )
    tail = catalog_list_share_tail(scripts=False)
    tail["__PLACE_SHARE_BAR__"] = ""
    title = page_title(page)
    description = page_description(page)
    return fill_placeholders(
        _B_TEMPLATE_PATH.read_text(encoding="utf-8"),
        {
            "__OG_TITLE__": esc(title),
            "__OG_DESCRIPTION__": esc(description),
            "__DESCRIPTION__": esc(description),
            "__CANONICAL__": esc(canonical),
            "__OG_URL__": esc(canonical),
            "__OG_IMAGE__": esc(og_image),
            "__LANG__": "ru",
            "__OG_LOCALE__": "ru_RU",
            "__ROBOTS__": "index, follow" if page["listed"] else "noindex, follow",
            "__HEAD_EXTRA__": f'<link rel="stylesheet" href="/static/share/trainer-page.css?v={TRAINER_PAGE_STYLE_VERSION}" />',
            "__JSONLD__": jsonld(page, canonical=canonical, base_url=base_url) if page["listed"] else "{}",
            "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
            "__PUBLIC_ANALYTICS_HEAD__": public_analytics_head_html_from_settings(),
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__SITE_FOOTER__": render_site_footer_html(
                context_html='<div class="elsewhere"><a href="/">Массовое катание по всей Беларуси</a></div>',
            ),
            "__BODY__": body,
            "__PAGE_VIEW_BEACON__": public_page_view_beacon_script(surface=TRAINER_SURFACE, city_id=None),
            "__GLIDE_CITY_PIN__": "",
            **tail,
        },
    )


# Хэш содержимого, не ручной номер: правка CSS сама сбрасывает кэш браузера.
TRAINER_PAGE_STYLE_VERSION = _file_version("static/share/trainer-page.css")
