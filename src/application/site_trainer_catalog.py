"""Каталог тренеров на сайте ``/c/{city}/trenery[/{направление}]`` (TASK-355, PDEC-033).

Вкладка-направление — наш слой над публичными услугами справочника (``services.is_public``,
vertical ice): таблица направлений и их тексты — ``catalog_directions`` (общая с ``/t/``). Город и цифры подставляются из данных.

* Кто виден — тот же предикат каталога, что у Mini App (``list_active_trainers_for_client``).
* Тренер во вкладке: есть услуга направления **и** (есть цена **или** ледовый каток в этом городе).
* Цена в карточке — тарифы услуги; «от» — ``trainer_min_price`` (тарифы, групповая, абонементы).
* Окна — те же, что на ``/t/`` (``_trainer_windows_on_arena``), запись — ``booking_url``.
* Число занятий тренера не показываем (решение владельца 2026-11-07); оценку — от 3 оценок.

Загрузка (``load_city_catalog``) — один раз на город; что показать во вкладке и с фильтром катка
(``catalog_view``) — чистая функция, её же берёт sitemap.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.style_b import _file_version
from src.application.catalog_directions import (  # noqa: F401 — реэкспорт для вызывающих и тестов
    _BY_KEY,
    _BY_SERVICE,
    _BY_SLUG,
    _Q_PAIR,
    _Q_PLAY,
    _Q_RENT,
    ALL,
    CATALOG_SEGMENT,
    DIRECTIONS,
    Direction,
    catalog_path,
    direction_by_key,
    direction_by_slug,
    own_service_direction,
    service_direction,
)
from src.application.ice_city_day import city_slug, format_price_minor, plural_ru
from src.application.style_b import esc
from src.shared.city_locative import city_locative
from src.shared.html_template import fill_placeholders, json_for_script

CATALOG_SURFACE = "trainer_catalog"
_B_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "static" / "share" / "b.html"
# Хэш содержимого, не ручной номер: правка CSS сама сбрасывает кэш браузера.
TRAINER_CATALOG_STYLE_VERSION = _file_version("static/share/trainer-catalog.css")
#: Сколько окон в карточке — дальше «Все окна и цены» на странице тренера.
CARD_WINDOWS = 3
#: Сколько катков в «Где проходят занятия».
ARENAS_SHOWN = 6
#: Оценку показываем, когда оценок хотя бы столько (решение владельца).
RATING_MIN_COUNT = 3


# ── Запись ───────────────────────────────────────────────────────────


def booking_url(
    base_url: str,
    trainer_id: int,
    *,
    city_id: int | None = None,
    slot_id: int | None = None,
    intent: str | None = None,
) -> str | None:
    """Единственное место, где каталог строит ссылку записи (окна и «Записаться»).

    Через учётный ``/open-telegram``: ``trainer_<id>`` — карточка тренера в Mini App,
    ``trainer_<id>_s_<slot>`` — сразу запись на это время (TASK-357; занято — «Время заняли»).
    Источник записи (TASK-351) — «каталог сайта» ``k<city_id>`` хвостом ``start_param``.
    ``intent`` — ``save`` / ``request``: Mini App сразу сохраняет тренера / открывает «Оставить заявку».
    """
    from src.application.booking_source import place_via
    from src.application.place_links import public_telegram_cta_url, trainer_start_param

    via = place_via(city_id=city_id, catalog=True)
    return public_telegram_cta_url(
        base_url,
        start_param=trainer_start_param(int(trainer_id), slot_id=slot_id, via=via, intent=intent),
        surface=CATALOG_SURFACE,
        city_id=city_id,
    )


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


async def _ice_arenas(
    session: AsyncSession, trainer_ids: list[int], city_id: int | None
) -> dict[int, list[dict[str, Any]]]:
    """Ледовые публичные катки тренеров в этом городе (лыжероллерная трасса и т. п. — мимо).

    ``city_id=None`` — во всех городах (нужно только понять, есть ли у тренера катки вне этого города).
    """
    from src.application.indexnow import SITEMAP_PLACE_WHERE_SQL
    from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

    if not trainer_ids:
        return {}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT ta.trainer_id, a.id, a.name, c.name AS city_name,
                       CASE WHEN {SITEMAP_PLACE_WHERE_SQL} THEN p.slug END AS slug
                FROM trainer_arenas ta
                JOIN arenas a ON a.id = ta.arena_id
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE ta.trainer_id = ANY(:tids) AND COALESCE(ta.is_public, true)
                  AND (CAST(:city AS integer) IS NULL OR a.city_id = :city) AND a.merged_into_arena_id IS NULL
                  AND COALESCE(a.venue_type, 'ice') = 'ice'
                  AND {PUBLIC_ARENA_VISIBLE_SQL}
                ORDER BY ta.trainer_id, a.sort_order NULLS LAST, a.id
                """
            ),
            {"tids": trainer_ids, "city": int(city_id) if city_id is not None else None, **public_scope_params()},
        )
    ).mappings().all()
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        name = str(r["name"] or "").strip()
        if name:
            out.setdefault(int(r["trainer_id"]), []).append(
                {"id": int(r["id"]), "name": name, "city_name": str(r["city_name"] or ""), "slug": r["slug"]}
            )
    return out


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


async def _usernames(session: AsyncSession, trainer_ids: list[int]) -> dict[int, str | None]:
    rows = await session.execute(
        text("SELECT id, telegram_username FROM trainers WHERE id = ANY(:ids)"), {"ids": trainer_ids}
    )
    return {int(i): u for i, u in rows.fetchall()}


def services_by_direction(services: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Услуги тренера по вкладкам (ключ направления), в порядке ``service_ids`` направления."""
    by_dir: dict[str, list[dict[str, Any]]] = {}
    for svc in services:
        key = service_direction(svc)
        if key:
            by_dir.setdefault(key, []).append(svc)
    for key, svcs in by_dir.items():
        ids_order = _BY_KEY[key].service_ids
        svcs.sort(key=lambda s: ids_order.index(int(s["service_id"])) if int(s["service_id"]) in ids_order else 99)
    return by_dir


def window_in_city(arena_id: Any, arena_cities: Mapping[int, int | None], city_id: int | None) -> bool:
    """Окно не показываем в городе, только если город его катка ИЗВЕСТЕН и другой (общее правило сайта и Mini App).

    Окно без катка (онлайн), без города или на катке, которого нет в ``arena_cities``, остаётся.
    """
    if city_id is None or arena_id is None:
        return True
    known = arena_cities.get(int(arena_id))
    return known is None or int(known) == int(city_id)


async def window_arena_cities(session: AsyncSession, windows: Sequence[Mapping[str, Any]]) -> dict[int, int | None]:
    """Город каждого катка из окон (любой каток: скрытый, слитый, не ледовый)."""
    ids = sorted({int(w["arena_id"]) for w in windows if w.get("arena_id") is not None})
    if not ids:
        return {}
    rows = await session.execute(text("SELECT id, city_id FROM arenas WHERE id = ANY(:ids)"), {"ids": ids})
    return {int(a): (int(c) if c is not None else None) for a, c in rows.fetchall()}


async def _primary_public_arenas(
    session: AsyncSession, trainer_ids: list[int], city_id: int
) -> dict[int, list[dict[str, Any]]]:
    """Основной каток тренера (``primary_arena_id``), если он публичный ледовый в этом городе.

    Каток, который тренер сам скрыл в ``trainer_arenas``, не берём. Нужен только окнам: записи в ``trainer_arenas``
    у основного катка может не быть, а окна на нём — главные окна тренера.
    """
    from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

    if not trainer_ids:
        return {}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.id AS trainer_id, a.id, a.name
                FROM trainers t
                JOIN arenas a ON a.id = t.primary_arena_id
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE t.id = ANY(:tids) AND a.city_id = :city AND a.merged_into_arena_id IS NULL
                  AND COALESCE(a.venue_type, 'ice') = 'ice'
                  AND NOT EXISTS (SELECT 1 FROM trainer_arenas ta
                                  WHERE ta.trainer_id = t.id AND ta.arena_id = a.id AND NOT COALESCE(ta.is_public, true))
                  AND {PUBLIC_ARENA_VISIBLE_SQL}
                """
            ),
            {"tids": trainer_ids, "city": int(city_id), **public_scope_params()},
        )
    ).mappings().all()
    return {
        int(r["trainer_id"]): [{"id": int(r["id"]), "name": str(r["name"] or "").strip()}] for r in rows
    }


def city_windows(
    windows: Sequence[Mapping[str, Any]],
    city_arenas: Sequence[Mapping[str, Any]],
    *,
    name_arena: bool,
    arena_cities: Mapping[int, int | None] | None = None,
    city_id: int | None = None,
) -> list[dict[str, Any]]:
    """Окна тренера для каталога города: только на публичных катках этого города (окно без катка — онлайн — остаётся).

    ``city_arenas`` — публичные катки тренера в городе плюс его публичный основной каток. Окно на катке, которого
    там нет (на модерации, скрытом, в другом городе), не показываем. Город катка сверяем общим правилом
    ``window_in_city``, если переданы ``arena_cities``/``city_id``.

    ``name_arena`` — у тренера несколько катков или они в разных городах: окну дописываем название катка.
    """
    names = {int(a["id"]): str(a["name"]) for a in city_arenas}
    out: list[dict[str, Any]] = []
    for w in windows:
        aid = w.get("arena_id")
        if aid is not None and int(aid) not in names:
            continue
        if arena_cities is not None and not window_in_city(aid, arena_cities, city_id):
            continue
        out.append({**w, "arena_name": names.get(int(aid)) if (name_arena and aid is not None) else None})
    return out


async def load_city_catalog(session: AsyncSession, city: Mapping[str, Any]) -> dict[str, Any]:
    """Все опубликованные тренеры города с тем, что нужно карточке и вкладкам."""
    from src.application.arena_media import attach_arena_media_payloads
    from src.application.arena_public_use_cases import _trainer_windows_on_arena
    from src.application.booking_source import place_via
    from src.application.site_trainer_page import contact_url, trainer_path
    from src.application.site_trainers import trainer_initial, trainer_name, trainer_photo_url
    from src.application.subscription_tier_use_cases import get_trainer_booking_availability
    from src.application.trainer_min_price import load_pass_offers
    from src.application.trainer_use_cases import list_active_trainers_for_client
    from src.shared.notification_hours import NOTIFICATION_TZ
    from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

    city_id = int(city["id"])
    items, _total = await list_active_trainers_for_client(session, limit=200, offset=0, city_id=city_id)
    bodies = [sanitize_trainer_for_public_catalog(raw) for raw in items]
    ids = [int(b["id"]) for b in bodies]
    arenas = await _ice_arenas(session, ids, city_id)
    all_arenas = await _ice_arenas(session, ids, None)
    primary = await _primary_public_arenas(session, ids, city_id)
    usernames = await _usernames(session, ids) if ids else {}
    passes = await load_pass_offers(session, ids)
    can_book: dict[int, bool] = {}
    for tid in ids:
        can_book[tid] = bool((await get_trainer_booking_availability(session, tid)).get("can_book"))
    windows = await _trainer_windows_on_arena(
        session, None, [t for t in ids if can_book[t]], timezone_name=NOTIFICATION_TZ
    )
    win_cities = await window_arena_cities(session, [w for ws in windows.values() for w in ws])
    trainers: list[dict[str, Any]] = []
    for order, body in enumerate(bodies):
        tid = int(body["id"])
        profile = body.get("profile") or {}
        name = trainer_name(body)
        by_dir = services_by_direction(body.get("services") or [])
        trainers.append(
            {
                "id": tid,
                "order": order,
                "name": name,
                "initial": trainer_initial(name),
                "photo_url": trainer_photo_url(body),
                "path": f"{trainer_path(tid, name)}?via={place_via(city_id=city_id, catalog=True)}",
                "experience_years": profile.get("experience_years"),
                "rating_avg": profile.get("rating_avg"),
                "rating_count": int(profile.get("rating_count") or 0),
                "education": education_line(profile.get("education")),
                "about": str(profile.get("description") or "").strip(),
                "arenas": arenas.get(tid, []),
                "services_by_dir": by_dir,
                "passes": passes.get(tid, []),
                "can_book": can_book[tid],
                "windows": (
                    city_windows(
                        windows.get(tid, []),
                        arenas.get(tid, [])
                        + [a for a in primary.get(tid, []) if a["id"] not in {x["id"] for x in arenas.get(tid, [])}],
                        name_arena=len(all_arenas.get(tid, [])) > 1,
                        arena_cities=win_cities,
                        city_id=city_id,
                    )
                    if can_book[tid]
                    else []
                ),
                "contact_url": contact_url(tid, usernames.get(tid), listed=True),
            }
        )
    arena_rows: dict[int, dict[str, Any]] = {}
    for t in trainers:
        for a in t["arenas"]:
            arena_rows.setdefault(a["id"], dict(a))
    rentals = await _rentals(session, list(arena_rows))
    media_items = list(arena_rows.values())
    await attach_arena_media_payloads(session, media_items)
    for a in media_items:
        a["rental_minor"] = rentals.get(a["id"])
    return {"city": dict(city), "trainers": trainers, "arenas": arena_rows}


# ── Что показать во вкладке ──────────────────────────────────────────


def direction_min_price(trainer: Mapping[str, Any], direction: Direction) -> tuple[int, str] | None:
    """«от» тренера в направлении (во «Всех» — по всем направлениям) — ``trainer_min_price``.

    Кандидаты — услуги направления (тарифы/цена, групповая) и абонементы тренера, покрывающие
    хоть одну из них. Ролики и ОФП/СФП — не направления, в «от» не входят.
    """
    from src.application.trainer_min_price import trainer_min_session_price

    by_dir = trainer["services_by_dir"]
    svcs = [s for k in ([direction.key] if direction is not ALL else list(by_dir)) for s in by_dir.get(k, [])]
    return trainer_min_session_price({"services": svcs, "passes": trainer.get("passes") or []})


def min_price_by_direction(trainer: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """``{"all" | slug: {"cents", "currency"}}`` — «от» по вкладкам для витрины Mini App (ключи — её)."""
    out: dict[str, dict[str, Any]] = {}
    for direction in (ALL, *DIRECTIONS):
        found = direction_min_price(trainer, direction)
        if found:
            out[direction.slug or "all"] = {"cents": found[0], "currency": found[1]}
    return out


def is_listed(trainer: Mapping[str, Any], direction: Direction) -> bool:
    """Правило показа: услуга направления и (цена услуги или каток). «Все» — хотя бы одно направление.

    «Цена» здесь — тариф или цена самой услуги, как ``serviceHasPrice`` витрины Mini App.
    """
    from src.application.trainer_min_price import service_price_from

    keys = list(trainer["services_by_dir"]) if direction is ALL else [direction.key]
    for key in keys:
        svcs = trainer["services_by_dir"].get(key)
        if not svcs:
            continue
        if trainer["arenas"] or any(service_price_from(s) is not None for s in svcs):
            return True
    return False


def _at(trainer: Mapping[str, Any], arena_id: int | None) -> bool:
    return arena_id is None or any(a["id"] == arena_id for a in trainer["arenas"])


def _card_windows(trainer: Mapping[str, Any], arena_id: int | None) -> list[dict[str, Any]]:
    wins = trainer.get("windows") or []
    if arena_id is not None:
        wins = [w for w in wins if w.get("arena_id") == arena_id]
    return wins


def listed_trainers(data: Mapping[str, Any], direction: Direction, arena_id: int | None = None) -> list[dict[str, Any]]:
    """Тренеры вкладки: сверху — с онлайн-записью по ближайшему окну, дальше — порядок каталога."""
    rows = [t for t in data["trainers"] if is_listed(t, direction) and _at(t, arena_id)]

    def key(t: Mapping[str, Any]) -> tuple[int, str, int]:
        wins = _card_windows(t, arena_id)
        return (0, str(wins[0]["starts_at"]), t["order"]) if wins else (1, "", t["order"])

    return sorted(rows, key=key)


def _id_set(data: Mapping[str, Any], direction: Direction) -> frozenset[int]:
    return frozenset(t["id"] for t in data["trainers"] if is_listed(t, direction))


def indexable(data: Mapping[str, Any], direction: Direction) -> bool:
    """В индексе — направление с тренерами (порог ≥1, PDEC-033 открытый вопрос). «Все» — если не
    повторяет одно из направлений тем же составом (в Минске сейчас все пятеро — «С нуля»)."""
    ids = _id_set(data, direction)
    if not ids:
        return False
    if direction is ALL:
        return all(_id_set(data, d) != ids for d in DIRECTIONS)
    return True


def sitemap_paths(data: Mapping[str, Any]) -> list[str]:
    name = str(data["city"]["name"])
    return [catalog_path(name, d) for d in (ALL, *DIRECTIONS) if indexable(data, d)]


async def sitemap_rows(session: AsyncSession) -> list[str]:
    """Пути каталога для sitemap: города, где есть опубликованные тренеры, × направления с тренерами."""
    from src.application.ice_city_day import list_public_cities
    from src.shared.catalog_visibility import CATALOG_LISTED_SQL

    city_ids = {
        int(r[0])
        for r in (
            await session.execute(
                text(
                    f"SELECT DISTINCT tc.city_id FROM trainer_cities tc JOIN trainers t ON t.id = tc.trainer_id "
                    f"LEFT JOIN trainer_profiles p ON p.trainer_id = t.id WHERE {CATALOG_LISTED_SQL}"
                )
            )
        ).fetchall()
    }
    out: list[str] = []
    for city in await list_public_cities(session):
        if int(city["id"]) in city_ids:
            out.extend(sitemap_paths(await load_city_catalog(session, city)))
    return out


# ── Вёрстка ──────────────────────────────────────────────────────────


def _n_trainers(n: int) -> str:
    return f"{n} {plural_ru(n, 'тренер', 'тренера', 'тренеров')}"


def _money(minor: int, currency: str = "BYN") -> str:
    return format_price_minor(int(minor), currency).replace(" ", " ")


def price_tiers(services: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]] | None:
    """Цена в карточке по тарифам направления: (сумма, подпись).

    «45 BYN ребёнок · 50 BYN взрослый» / «50 BYN · дети и взрослые» / «55 BYN за занятие». Берём
    первую услугу направления с ценой (у «С клюшкой» — хоккейное катание, потом ОХМ). Тарифы «на
    двоих» — на странице тренера. ``None`` — «Цену уточните у тренера».
    """
    for svc in services:
        cur = str(svc.get("currency_code") or "BYN")
        tiers = {str(t.get("tier_kind")): int(t["price_cents"]) for t in svc.get("price_tiers") or [] if t.get("price_cents")}
        child, adult = tiers.get("child"), tiers.get("adult")
        if child and adult:
            if child == adult:
                return [(_money(child, cur), "дети и взрослые")]
            return [(_money(child, cur), "ребёнок"), (_money(adult, cur), "взрослый")]
        if adult:
            return [(_money(adult, cur), "взрослый")]
        if child:
            return [(_money(child, cur), "ребёнок")]
        if tiers:
            continue
        cents = svc.get("price_cents")
        if cents and int(cents) > 0:
            return [(_money(int(cents), cur), "за занятие")]
    return None


def _rating_html(t: Mapping[str, Any]) -> str:
    avg, n = t.get("rating_avg"), int(t.get("rating_count") or 0)
    if not avg or n < RATING_MIN_COUNT:
        return ""
    who = plural_ru(n, "ученик оценил", "ученика оценили", "учеников оценили")
    return (
        f'<div class="tc-rate"><i aria-hidden="true">★</i>{float(avg):.1f}'.replace(".", ",")
        + f" <span>· {n} {who} занятия</span></div>"
    )


def _arenas_check(arenas: Sequence[Mapping[str, Any]]) -> str:
    names = [str(a["name"]) for a in arenas]
    if not names:
        return ""
    if len(names) > 2:
        rest = len(names) - 2
        return f"Каток: {names[0]}, {names[1]} и ещё {rest} {plural_ru(rest, 'каток', 'катка', 'катков')}"
    return "Каток: " + ", ".join(names)


def _min_price_basis(t: Mapping[str, Any], cents: int) -> str:
    """Пометка к «от», если минимум дают не обычные занятия: иначе «от 30» спорит с 45/50 на странице."""
    from src.application.trainer_min_price import service_price_from

    svcs = [s for rows in t["services_by_dir"].values() for s in rows]
    singles = [p for p in (service_price_from(s) for s in svcs) if p is not None]
    if singles and min(singles) <= cents:
        return ""
    if any(int(s.get("group_price_cents") or 0) == cents for s in svcs):
        return "в группе"
    return "по абонементу"


def _price_html(t: Mapping[str, Any], direction: Direction) -> str:
    if direction is ALL:
        label = "Занятие"
        found = direction_min_price(t, ALL)
        basis = _min_price_basis(t, found[0]) if found else ""
        note = f" <small>{esc(basis)}</small>" if basis else ""
        val = f'<div class="tc-val">от {esc(_money(*found))}{note}</div>' if found else ""
    else:
        label = "Занятие · " + direction.short
        tiers = price_tiers(t["services_by_dir"].get(direction.key, []))
        val = (
            '<div class="tc-tiers">'
            + "".join(f'<div class="tc-val">{esc(v)} <small>{esc(sub)}</small></div>' for v, sub in tiers)
            + "</div>"
            if tiers
            else ""
        )
    if not val:
        val = '<div class="tc-no">Цену уточните у тренера</div>'
    return f'<div class="tc-price"><div><div class="tc-lbl">{esc(label)}</div>{val}</div></div>'


def _window_label(w: Mapping[str, Any]) -> str:
    base = f'{w["day"]}, {w["time"]}'
    return f'{base} · {w["arena_name"]}' if w.get("arena_name") else base


_ICON_HEART = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'


def _card_html(
    t: Mapping[str, Any], direction: Direction, *, base_url: str, city_id: int, arena_id: int | None
) -> str:
    photo = t.get("photo_url")
    ph = (
        f'<img class="tc-ph" src="{esc(photo)}" alt="" width="128" height="148" loading="lazy" decoding="async" />'
        if photo
        else f'<span class="tc-ph tc-ph--mono" aria-hidden="true">{esc(t["initial"])}</span>'
    )
    years = t.get("experience_years")
    badge = (
        f'<span class="tc-badge">Тренирует {int(years)} {plural_ru(int(years), "год", "года", "лет")}</span>'
        if years and int(years) > 0
        else ""
    )
    dirs = [d.short for d in DIRECTIONS if d.key in t["services_by_dir"]]
    dirs_text = " · ".join(dirs)
    dirs_html = f'<div class="tc-dirs">{esc(dirs_text[:1].upper() + dirs_text[1:])}</div>' if dirs_text else ""
    checks = [c for c in (t.get("education"), _arenas_check(t["arenas"])) if c]
    checks_html = (
        '<ul class="tc-checks">' + "".join(f"<li>{esc(c)}</li>" for c in checks) + "</ul>" if checks else ""
    )
    about = f'<p class="tc-about">{esc(t["about"])}</p>' if t.get("about") else ""
    wins = _card_windows(t, arena_id)[:CARD_WINDOWS]
    book = booking_url(base_url, int(t["id"]), city_id=city_id) if wins else None
    if wins and book:
        act = (
            '<div><div class="tc-lbl">Записаться на время</div><div class="tc-slots">'
            + "".join(
                f'<a class="tc-slot" href="{esc(booking_url(base_url, int(t["id"]), city_id=city_id, slot_id=w.get("slot_id")))}" rel="nofollow" '
                f'aria-label="Записаться: {esc(_window_label(w))}">{esc(_window_label(w))}</a>'
                for w in wins
            )
            + "</div></div>"
        )
    elif t.get("contact_url"):
        act = f'<div class="tc-act"><a class="b-tgbtn tc-btn" href="{esc(t["contact_url"])}" rel="nofollow">Написать в Telegram</a></div>'
    elif t.get("can_book"):
        open_url = booking_url(base_url, int(t["id"]), city_id=city_id)
        act = (
            f'<div class="tc-act"><a class="b-tgbtn tc-btn" href="{esc(open_url)}" rel="nofollow">Записаться в Telegram</a></div>'
            if open_url
            else ""
        )
    else:
        act = ""
    if not wins:
        # Времени нет — рядом с «Написать» / «Записаться» тихая «Оставить заявку» (бот ведёт её тренеру).
        req = booking_url(base_url, int(t["id"]), city_id=city_id, intent="request")
        if req:
            btn = f'<a class="tc-btn tc-btn--ghost" href="{esc(req)}" rel="nofollow">Оставить заявку</a>'
            act = act.replace("</div>", btn + "</div>", 1) if act else f'<div class="tc-act">{btn}</div>'
    save_url = booking_url(base_url, int(t["id"]), city_id=city_id, intent="save")
    save = (
        f'<a class="tc-save" href="{esc(save_url)}" rel="nofollow" title="Сохранить тренера в Telegram" '
        f'aria-label="Сохранить: {esc(t["name"])} — в Telegram">{_ICON_HEART}</a>'
        if save_url
        else ""
    )
    return (
        '<article class="tc">'
        f'<a class="tc-stretch" href="{esc(t["path"])}" aria-label="{esc(t["name"])} — страница тренера"></a>'
        f"{save}"
        f'<div class="tc-top">{ph}<div class="tc-head">{badge}<h3 class="tc-name">{esc(t["name"])}</h3>{dirs_html}{_rating_html(t)}</div></div>'
        f"{checks_html}{about}{_price_html(t, direction)}{act}"
        '<span class="tc-more">Расписание и цены →</span>'
        "</article>"
    )


def _faq_answer(q: str, a: str | None, ctx: Mapping[str, Any]) -> str | None:
    """HTML ответа; ``None`` — данных нет, вопроса нет."""
    if a is not None:
        return esc(a)
    if q == _Q_RENT:
        rents = ctx["rentals"]
        if not rents:
            return None
        return esc("Возьмите в прокате: " + ", ".join(f"в {n} — {p}" for n, p in rents[:3]) + ".")
    if q == _Q_PAIR:
        n = ctx["pairs"]
        if not n:
            return None
        return esc(f"Да, у {n} {plural_ru(n, 'тренера', 'тренеров', 'тренеров')} есть цена «взрослый + ребёнок» — она на странице тренера.")
    if q == _Q_PLAY:
        return f'Расписание ОХМ — в разделе «С клюшкой» на <a href="{esc(ctx["city_href"])}">странице города</a>.'
    return None


def _has_pair_tier(t: Mapping[str, Any], direction: Direction) -> bool:
    keys = list(t["services_by_dir"]) if direction is ALL else [direction.key]
    return any(
        str(tier.get("tier_kind")) == "adult_and_child"
        for k in keys
        for s in t["services_by_dir"].get(k, [])
        for tier in s.get("price_tiers") or []
    )


def _arena_dialog(
    data: Mapping[str, Any], direction: Direction, pool: list[dict[str, Any]], arena_id: int | None, city_name: str
) -> str:
    counts: dict[int, int] = {}
    for t in pool:
        for a in t["arenas"]:
            counts[a["id"]] = counts.get(a["id"], 0) + 1
    arenas = data["arenas"]
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], str(arenas[kv[0]]["name"])))
    items = [
        f'<li><a href="{esc(catalog_path(city_name, direction))}"{" class=on aria-current=true" if arena_id is None else ""}>Все катки<b>{len(pool)}</b></a></li>'
    ] + [
        f'<li><a href="{esc(catalog_path(city_name, direction, arena_id=aid))}"{" class=on aria-current=true" if aid == arena_id else ""}>'
        f"{esc(arenas[aid]['name'])}<b>{n}</b></a></li>"
        for aid, n in rows
    ]
    sub = (
        "Цифра — сколько тренеров занимаются на катке."
        if direction is ALL
        else f"Цифра — сколько тренеров «{direction.tab}» занимаются на катке."
    )
    current = arenas[arena_id]["name"] if arena_id in arenas else "Все катки"
    clear = (
        f'<a class="tcat-chip" href="{esc(catalog_path(city_name, direction))}" aria-label="Сбросить каток">✕</a>'
        if arena_id is not None
        else ""
    )
    return (
        '<div class="tcat-arow"><span>Каток:</span>'
        f'<button class="tcat-chip" type="button" data-tcat-open aria-haspopup="dialog">{esc(current)} ▾</button>{clear}</div>'
        '<dialog class="tcat-dlg" id="tcat-dlg" aria-label="Каток"><div>'
        '<div class="tcat-dh"><b>Где удобно заниматься?</b>'
        '<button type="button" class="tcat-x" data-tcat-close aria-label="Закрыть">✕</button></div>'
        f'<span class="tcat-dsub">{esc(sub)}</span><ul>{"".join(items)}</ul></div></dialog>'
    )


_DIALOG_SCRIPT = (
    "<script>(function(){var d=document.getElementById('tcat-dlg');if(!d||!d.showModal)return;"
    "document.addEventListener('click',function(e){var t=e.target;"
    "if(t.closest&&t.closest('[data-tcat-open]')){d.showModal();}"
    "else if(t===d||(t.closest&&t.closest('[data-tcat-close]'))){d.close();}});})();</script>"
)


def _sec(title: str, body: str, *, klass: str = "") -> str:
    if not body:
        return ""
    return f'<section class="tcat-sec{(" " + klass) if klass else ""}"><h2 class="b-h2 tcat-h2">{esc(title)}</h2>{body}</section>'


_AFTER = (
    ("Откроется Telegram", "Запись идёт в Glide внутри Telegram — устанавливать ничего не нужно."),
    ("Тренер подтвердит", "Подтверждение придёт сообщением в Telegram."),
    ("Оплата на месте", "Платите тренеру при встрече. Билет на каток — отдельно, на кассе."),
    ("Планы поменялись", "Отмените запись в разделе «Мои записи»."),
)


def render_catalog_page(
    data: Mapping[str, Any], direction: Direction, *, base_url: str, arena_id: int | None = None
) -> str:
    from src.application.catalog_home_page import catalog_home_og_image_url
    from src.application.catalog_list_share import catalog_list_share_tail
    from src.application.place_links import breadcrumb_script, place_page_url
    from src.application.public_analytics import public_analytics_head_html_from_settings
    from src.application.public_site_footer import render_site_footer_html
    from src.application.public_web_cta import public_page_view_beacon_script
    from src.application.style_b import COMPONENTS_VERSION, STYLE_VERSION, TOKENS_VERSION, media_url, public_fonts_head_html

    base = (base_url or "").rstrip("/")
    city = data["city"]
    city_name = str(city["name"])
    city_id = int(city["id"])
    loc = city_locative(city_name)
    in_city = f"в {loc}" if loc else city_name
    arenas = data["arenas"]
    if arena_id is not None and arena_id not in arenas:
        arena_id = None
    everyone = listed_trainers(data, ALL)
    one = len(everyone) == 1
    pool = listed_trainers(data, direction)
    shown = listed_trainers(data, direction, arena_id)
    canonical = f"{base}{catalog_path(city_name, direction)}"
    city_href = f"/c/{city_slug(city_name)}"

    h1 = "Тренер по катанию на коньках" if one and direction is ALL else direction.h1
    prices = [p for p in (direction_min_price(t, direction) for t in shown) if p]
    facts = [f"<span><b>{esc(_n_trainers(len(shown)))}</b></span>"]
    if prices:
        low = min(prices)
        facts.append(f"<span>от <b>{esc(_money(*low))}</b> за занятие</span>")
    facts.append("<span>оплата на месте</span>")
    crumbs_html = (
        '<nav class="tcat-crumbs" aria-label="Навигация">'
        f'<a href="{esc(city_href)}">{esc(city_name)}</a> › '
        + (
            f'<a href="{esc(catalog_path(city_name))}">Тренеры</a> › <span>{esc(direction.crumb)}</span>'
            if direction is not ALL
            else "<span>Тренеры</span>"
        )
        + "</nav>"
    )
    hero = (
        '<section class="tcat-hero">'
        f'<span class="tcat-eyebrow">Учиться с тренером · {esc(city_name)}</span>'
        f'<h1 class="tcat-h1">{esc(h1)} <em>{esc(in_city)}</em></h1>'
        f'<p class="tcat-lead">{esc(direction.lead)}</p>'
        f'<div class="tcat-facts">{"".join(facts)}</div></section>'
    )

    controls = ""
    if not one and everyone:
        controls += _arena_dialog(data, direction, pool, arena_id, city_name)
        tabs = []
        for d in (ALL, *DIRECTIONS):
            n = len(listed_trainers(data, d, arena_id))
            if not n and d is not direction:
                continue
            on = d is direction
            tabs.append(
                f'<a class="tcat-tab{" on" if on else ""}" href="{esc(catalog_path(city_name, d, arena_id=arena_id))}"'
                f'{" aria-current=page" if on else ""}>{esc(d.tab)}<b>{n}</b></a>'
            )
        controls += f'<nav class="tcat-tabs" aria-label="Направления">{"".join(tabs)}</nav>'
    if len(shown) > 1:
        controls += '<p class="tcat-sortnote">Сверху — тренеры с онлайн-записью, по ближайшему свободному времени.</p>'

    if shown:
        grid = '<div class="tcat-grid">' + "".join(
            _card_html(t, direction, base_url=base, city_id=city_id, arena_id=arena_id) for t in shown
        ) + "</div>"
        grid += (
            '<div class="tcat-request"><b>Не подошло время?</b>'
            "<span>Напишите тренеру — он предложит своё.</span></div>"
        )
    elif arena_id is not None:
        aname = str(arenas[arena_id]["name"])
        if direction is ALL:
            grid = (
                f'<div class="tcat-empty"><b>{esc(aname)}: тренеров здесь пока нет</b>'
                f'<div class="tcat-empty__act"><a class="tcat-ghost" href="{esc(catalog_path(city_name))}">Все тренеры {esc(in_city)}</a></div></div>'
            )
        else:
            grid = (
                f'<div class="tcat-empty"><b>{esc(aname)}: тренеров «{esc(direction.tab)}» здесь пока нет</b>'
                f'<span>Посмотрите всех тренеров этого катка или тренеров «{esc(direction.tab)}» на других катках.</span>'
                '<div class="tcat-empty__act">'
                f'<a class="tcat-ghost" href="{esc(catalog_path(city_name, ALL, arena_id=arena_id))}">Все тренеры этого катка</a>'
                f'<a class="tcat-ghost" href="{esc(catalog_path(city_name, direction))}">«{esc(direction.tab)}» на всех катках</a>'
                "</div></div>"
            )
    else:
        tail = f"«{direction.tab}» " if direction is not ALL else ""
        link = (
            f'<div class="tcat-empty__act"><a class="tcat-ghost" href="{esc(catalog_path(city_name))}">Все тренеры {esc(in_city)}</a></div>'
            if direction is not ALL and everyone
            else ""
        )
        grid = f'<div class="tcat-empty"><b>{esc(f"Тренеров {tail}{in_city} пока нет")}</b>{link}</div>'

    body = '<div class="tcat">' + crumbs_html + hero + controls + grid
    if pool:
        body += _sec(
            "Что будет после записи",
            '<div class="tcat-after">'
            + "".join(f"<div><i>{i}</i><b>{esc(b)}</b><span>{esc(s)}</span></div>" for i, (b, s) in enumerate(_AFTER, 1))
            + "</div>",
        )
    body += _sec(
        "Как проходит первое занятие",
        '<div class="tcat-steps">'
        + "".join(f'<div class="tcat-step"><b>{esc(b)}</b><span>{esc(s)}</span></div>' for b, s in direction.steps)
        + "</div>",
    )

    # Катки направления (без фильтра): число тренеров, прокат — из сеансов катка.
    counts: dict[int, int] = {}
    for t in pool:
        for a in t["arenas"]:
            counts[a["id"]] = counts.get(a["id"], 0) + 1
    arena_order = sorted(counts, key=lambda aid: (-counts[aid], str(arenas[aid]["name"])))
    rentals = [
        (str(arenas[aid]["name"]), _money(arenas[aid]["rental_minor"]))
        for aid in arena_order
        if arenas[aid].get("rental_minor")
    ]
    ctx = {
        "rentals": rentals,
        "pairs": sum(1 for t in pool if _has_pair_tier(t, direction)),
        "city_href": city_href,
    }
    faq_items = []
    for q, a in direction.faq:
        ans = _faq_answer(q, a, ctx)
        if ans is not None:
            faq_items.append((q, ans))
    body += _sec(
        "Частые вопросы",
        '<div class="tcat-faq">'
        + "".join(
            f'<details{" open" if i == 0 else ""}><summary>{esc(q)}</summary><p>{a}</p></details>'
            for i, (q, a) in enumerate(faq_items)
        )
        + "</div>"
        if faq_items
        else "",
    )

    cards = []
    for aid in arena_order[:ARENAS_SHOWN]:
        a = arenas[aid]
        img = media_url(a.get("hero"), size="card")
        img_html = f'<img src="{esc(img)}" alt="" loading="lazy" decoding="async" />' if img else ""
        rent = f"Прокат — {_money(a['rental_minor'])} · " if a.get("rental_minor") else ""
        inner = (
            f"{img_html}<div><b>{esc(a['name'])}</b><span>{esc(_n_trainers(counts[aid]))}</span>"
            + (f"<em>{esc(rent)}расписание ›</em>" if a.get("slug") else (f"<em>{esc(rent[:-3])}</em>" if rent else ""))
            + "</div>"
        )
        if a.get("slug"):
            href = place_page_url(base_url=base, city_name=a["city_name"], slug=a["slug"])
            cards.append(f'<a class="tcat-ar{"" if img else " tcat-ar--noimg"}" href="{esc(href)}">{inner}</a>')
        else:
            cards.append(f'<div class="tcat-ar{"" if img else " tcat-ar--noimg"}">{inner}</div>')
    body += _sec("Где проходят занятия", f'<div class="tcat-arenas">{"".join(cards)}</div>' if cards else "")

    if not one:
        others = []
        for d in DIRECTIONS:
            if d is direction:
                continue
            rows = listed_trainers(data, d)
            if not rows:
                continue
            ps = [p for p in (direction_min_price(t, d) for t in rows) if p]
            price = f"от {_money(*min(ps))}" if ps else "цену уточните у тренера"
            others.append(
                f'<a class="tcat-db" href="{esc(catalog_path(city_name, d))}"><h3>{esc(d.crumb)}</h3>'
                f'<span class="tcat-db__p">{esc(price)}</span><span>{esc(d.lead)}</span>'
                f'<span class="tcat-db__go">{esc(_n_trainers(len(rows)))} →</span></a>'
            )
        body += _sec(f"Ещё {in_city}", f'<div class="tcat-dirsb">{"".join(others)}</div>' if others else "")

    coach_title = f"Тренируете {in_city}?" if loc else "Тренируете?"
    body += (
        f'<div class="tcat-band"><div><b>{esc(coach_title)}</b>'
        "<span>Бесплатная страница тренера и ссылка для ваших учеников.</span></div>"
        '<a class="b-tgbtn tcat-band__btn" href="/trainers?utm_source=glide&amp;utm_medium=trainer_catalog">Создать страницу</a></div>'
    )
    body += "</div>"
    if not one and everyone:
        body += _DIALOG_SCRIPT

    crumbs = [("Glideclub", f"{base}/"), (city_name, f"{base}{city_href}"), ("Тренеры", f"{base}{catalog_path(city_name)}")]
    if direction is not ALL:
        crumbs.append((direction.crumb, canonical))
    body += breadcrumb_script(canonical, crumbs)

    title = f"{h1} {in_city} · Glideclub".replace(" ", " ")
    desc_bits = [direction.lead]
    if pool:
        ps = [p for p in (direction_min_price(t, direction) for t in pool) if p]
        desc_bits.append(
            _n_trainers(len(pool)).replace(" ", " ")
            + (f", от {_money(*min(ps))} за занятие".replace(" ", " ") if ps else "")
            + ". Запись в Telegram, оплата тренеру на месте."
        )
    description = " ".join(desc_bits)
    if len(description) > 155:
        description = description[:154].rstrip() + "…"
    ld = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"{h1} {in_city}".replace(" ", " "),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": t["name"], "url": f"{base}{t['path']}"}
            for i, t in enumerate(pool)
        ],
    }
    tail = catalog_list_share_tail(scripts=False)
    tail["__PLACE_SHARE_BAR__"] = ""
    return fill_placeholders(
        _B_TEMPLATE_PATH.read_text(encoding="utf-8"),
        {
            "__OG_TITLE__": esc(title),
            "__OG_DESCRIPTION__": esc(description),
            "__DESCRIPTION__": esc(description),
            "__CANONICAL__": esc(canonical),
            "__OG_URL__": esc(canonical),
            "__OG_IMAGE__": esc(catalog_home_og_image_url(base)),
            "__LANG__": "ru",
            "__OG_LOCALE__": "ru_RU",
            "__ROBOTS__": "index, follow" if indexable(data, direction) else "noindex, follow",
            "__HEAD_EXTRA__": f'<link rel="stylesheet" href="/static/share/trainer-catalog.css?v={TRAINER_CATALOG_STYLE_VERSION}" />',
            "__JSONLD__": json_for_script(ld) if pool else "{}",
            "__PUBLIC_FONTS_HEAD__": public_fonts_head_html(),
            "__PUBLIC_ANALYTICS_HEAD__": public_analytics_head_html_from_settings(),
            "__TOKENS_V__": TOKENS_VERSION,
            "__STYLE_V__": STYLE_VERSION,
            "__COMPONENTS_V__": COMPONENTS_VERSION,
            "__SITE_FOOTER__": render_site_footer_html(
                context_html=f'<div class="elsewhere"><a href="{esc(city_href)}">Катание {esc(in_city)}</a></div>',
            ),
            "__BODY__": body,
            "__PAGE_VIEW_BEACON__": public_page_view_beacon_script(surface=CATALOG_SURFACE, city_id=city_id),
            "__GLIDE_CITY_PIN__": "",
            **tail,
        },
    )


def parse_arena_param(raw: str | None) -> int | None:
    value = (raw or "").strip()
    return int(value) if re.fullmatch(r"[1-9][0-9]{0,8}", value) else None

