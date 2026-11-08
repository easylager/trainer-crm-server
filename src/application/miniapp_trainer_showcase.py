"""Витрина тренеров в Mini App (TASK-357, PDEC-033): одна выдача на город для экрана 1.

Список тренеров — тот же, что ``/api/public/trainers`` (``list_active_trainers_for_client``: кто
опубликован, тот виден). Сверху — только цифры, которых в той выдаче нет, а дизайн без них
невозможен:

* ``min_session_price_cents`` — «от N BYN», единственный источник — ``trainer_min_price``;
* ``min_price_by_direction`` — «от» по вкладкам (``{"all" | slug: {cents, currency}}``): тарифы,
  групповые и абонементы, покрывающие услуги вкладки (``site_trainer_catalog.direction_min_price``,
  та же цифра, что на сайте). Клиент берёт минимум по показанным тренерам, сам не считает;
* ``glide_since`` — «В Glide с <месяц год>»: месяц первого завершённого занятия у тренера, без
  записей тренера к самому себе и без песочницы. Число занятий не отдаём — решение владельца;
* ``windows`` — ближайшие свободные окна на одного (те же, что у страницы тренера ``/t/…``);
* ``arenas`` — только лёд (``venue_type = 'ice'``) с прокатом, если он известен по сеансам катка.

Направления (вкладки) и их тексты — слой «пишем мы», живут в клиенте; сервер отдаёт услуги
тренера с ``is_public``, чтобы своя услуга без направления не попадала во вкладки.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_directions import service_title, split_service_summary
from src.application.trainer_client_invite_tracking import sql_booking_not_self

#: Сколько тренеров берём в выдачу. Каталог крошечный (6 опубликованных); пагинация — открытый вопрос эпика.
SHOWCASE_LIMIT = 50
#: Окно цен проката: сеансы катка за этот срок вперёд.
_RENTAL_DAYS = 21


async def _glide_since(session: AsyncSession, trainer_ids: list[int]) -> dict[int, str]:
    """``{trainer_id: 'YYYY-MM'}`` — месяц первого завершённого занятия (не самозапись, не песочница)."""
    if not trainer_ids:
        return {}
    rows = await session.execute(
        text(
            f"""
            SELECT b.trainer_id, MIN(s.slot_date) AS first_date
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN trainers t ON t.id = b.trainer_id
            WHERE b.trainer_id = ANY(:tids)
              AND b.status = 'completed'
              AND COALESCE(b.is_sandbox, false) = false
              AND {sql_booking_not_self(booking_alias="b", trainer_id_expr="t.id")}
            GROUP BY b.trainer_id
            """
        ),
        {"tids": trainer_ids},
    )
    out: dict[int, str] = {}
    for tid, first_date in rows.fetchall():
        if first_date is not None:
            out[int(tid)] = f"{first_date.year:04d}-{first_date.month:02d}"
    return out


async def _ice_arenas(session: AsyncSession, arena_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Ледовые площадки по id: имя и прокат (минимум ``price_rental_minor`` по ближайшим сеансам)."""
    if not arena_ids:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT a.id, a.name, a.city_id,
                   (SELECT MIN(i.price_rental_minor) FROM ice_sessions i
                     WHERE i.arena_id = a.id AND i.price_rental_minor IS NOT NULL
                       AND i.starts_at_utc > NOW()
                       AND i.starts_at_utc < NOW() + make_interval(days => :days)) AS rental_minor,
                   (SELECT i.currency_code FROM ice_sessions i
                     WHERE i.arena_id = a.id AND i.price_rental_minor IS NOT NULL
                       AND i.starts_at_utc > NOW()
                     ORDER BY i.starts_at_utc LIMIT 1) AS rental_currency
            FROM arenas a
            WHERE a.id = ANY(:ids)
              AND COALESCE(a.venue_type, 'ice') = 'ice'
              AND a.merged_into_arena_id IS NULL
            """
        ),
        {"ids": arena_ids, "days": _RENTAL_DAYS},
    )
    out: dict[int, dict[str, Any]] = {}
    for aid, name, arena_city, rental_minor, rental_currency in rows.fetchall():
        label = str(name or "").strip()
        if not label:
            continue
        out[int(aid)] = {
            "id": int(aid),
            "name": label,
            "city_id": int(arena_city) if arena_city is not None else None,
            "rental_cents": int(rental_minor) if rental_minor else None,
            "rental_currency": str(rental_currency or "BYN") if rental_minor else None,
        }
    return out


async def _service_catalog_info(session: AsyncSession, service_ids: set[int]) -> dict[int, tuple[bool, str | None]]:
    """``service_id → (is_public, client_summary)`` одним запросом на всю выдачу."""
    if not service_ids:
        return {}
    rows = await session.execute(
        text("SELECT id, COALESCE(is_public, true), client_summary FROM services WHERE id = ANY(:ids)"),
        {"ids": sorted(service_ids)},
    )
    return {int(r[0]): (bool(r[1]), r[2]) for r in rows.fetchall()}


def _service_out(svc: dict[str, Any], catalog: dict[int, tuple[bool, str | None]]) -> dict[str, Any]:
    sid = int(svc["service_id"])
    is_public, summary = catalog.get(sid, (False, None))
    # Наш текст из справочника — только у публичных услуг: у своей услуги тренера его нет.
    hook, body = split_service_summary(summary) if is_public else ("", "")
    name = str(svc.get("service_name") or "").strip()
    return {
        "service_id": sid,
        "service_name": name,
        "title": service_title(name),
        "is_public": is_public,
        "summary_hook": hook,
        "summary_body": body,
        "client_notice": str(svc.get("client_notice") or "").strip() or None,
        # Своя услуга тренера, привязанная админом к направлению (TASK-353): во вкладке этой услуги.
        "direction_service_id": svc.get("direction_service_id"),
        "is_online": bool(svc.get("is_online")),
        "price_cents": svc.get("price_cents"),
        # Группа: сервер записывает COALESCE(group_price_cents, price_cents) — строка оплаты показывает то же.
        "group_price_cents": svc.get("group_price_cents"),
        "currency_code": svc.get("currency_code") or "BYN",
        "description": svc.get("description"),
        "price_tiers": [
            {
                "id": int(t["id"]),
                "tier_kind": t.get("tier_kind"),
                "label": t.get("label"),
                "price_cents": int(t["price_cents"]),
                "currency_code": t.get("currency_code") or svc.get("currency_code") or "BYN",
            }
            for t in svc.get("price_tiers") or []
        ],
    }


async def load_trainer_showcase(session: AsyncSession, *, city_id: int | None) -> dict[str, Any]:
    """Тренеры города для витрины. Фильтр катка и вкладки клиент считает сам — по этим данным."""
    from src.application.arena_public_use_cases import _trainer_windows_on_arena
    from src.application.site_trainer_catalog import (
        min_price_by_direction,
        services_by_direction,
        window_arena_cities,
        window_in_city,
    )
    from src.application.site_trainer_page import contact_url
    from src.application.site_trainers import trainer_initial, trainer_name, trainer_photo_url
    from src.application.subscription_tier_use_cases import get_trainer_booking_availability
    from src.application.trainer_min_price import enrich_min_session_price
    from src.application.trainer_use_cases import list_active_trainers_for_client
    from src.shared.notification_hours import NOTIFICATION_TZ
    from src.shared.public_trainer_payload import sanitize_trainer_for_public_catalog

    raw_items, _total = await list_active_trainers_for_client(
        session, limit=SHOWCASE_LIMIT, offset=0, city_id=city_id, order_by="rating"
    )
    items = [sanitize_trainer_for_public_catalog(t) for t in raw_items]
    passes = await enrich_min_session_price(session, items)
    ids = [int(t["id"]) for t in items]
    since = await _glide_since(session, ids)
    arena_ids = sorted({int(a) for t in items for a in (t.get("arena_ids") or [])})
    arenas = await _ice_arenas(session, arena_ids)
    catalog = await _service_catalog_info(
        session, {int(s["service_id"]) for t in items for s in t.get("services") or []}
    )
    usernames: dict[int, str | None] = {}
    if ids:
        rows = await session.execute(
            text("SELECT id, telegram_username FROM trainers WHERE id = ANY(:ids)"), {"ids": ids}
        )
        usernames = {int(r[0]): r[1] for r in rows.fetchall()}

    can_book: dict[int, bool] = {}
    for tid in ids:
        can_book[tid] = bool((await get_trainer_booking_availability(session, tid)).get("can_book"))
    bookable = [tid for tid in ids if can_book[tid]]
    windows = (
        await _trainer_windows_on_arena(session, None, bookable, timezone_name=NOTIFICATION_TZ) if bookable else {}
    )

    win_cities = await window_arena_cities(session, [w for ws in windows.values() for w in ws])

    out: list[dict[str, Any]] = []
    for t in items:
        tid = int(t["id"])
        profile = t.get("profile") or {}
        name = trainer_name(t)
        out.append(
            {
                "id": tid,
                "name": name,
                "first_name": str(profile.get("first_name") or "").strip() or name,
                "initial": trainer_initial(name),
                "photo_url": trainer_photo_url(t),
                "experience_years": profile.get("experience_years"),
                "description": str(profile.get("description") or "").strip(),
                "education": str(profile.get("education") or "").strip(),
                "rating_avg": profile.get("rating_avg"),
                "rating_count": int(profile.get("rating_count") or 0),
                "session_duration_minutes": profile.get("session_duration_minutes"),
                "glide_since": since.get(tid),
                "can_book": can_book[tid],
                "contact_url": contact_url(tid, usernames.get(tid), listed=True),
                "min_session_price_cents": t.get("min_session_price_cents"),
                "min_session_price_currency": t.get("min_session_price_currency"),
                "min_price_by_direction": min_price_by_direction(
                    {"services_by_dir": services_by_direction(t.get("services") or []), "passes": passes.get(tid, [])}
                ),
                "services": [_service_out(s, catalog) for s in t.get("services") or []],
                "arenas": [arenas[a] for a in (t.get("arena_ids") or []) if a in arenas],
                "windows": [
                    {k: w.get(k) for k in ("slot_id", "arena_id", "starts_at", "ends_at", "time", "day")}
                    for w in windows.get(tid, [])
                    if window_in_city(w.get("arena_id"), win_cities, city_id)
                ],
            }
        )
    return {"city_id": city_id, "items": out}
