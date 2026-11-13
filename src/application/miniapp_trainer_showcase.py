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

Под флагом ``unified_trainer_card_enabled`` (единая карточка) ещё ``reviews`` и ``class_photos``
(TASK-416) — те же отзывы и фото, что у страницы ``/t/``. Флаг выключен — этих ключей нет.

Направления (вкладки) и их тексты — слой «пишем мы», живут в клиенте; сервер отдаёт услуги
тренера с ``is_public``, чтобы своя услуга без направления не попадала во вкладки.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_directions import service_title, split_service_summary
from src.application.site_trainer_page import education_line
from src.application.trainer_client_invite_tracking import sql_booking_not_self
from src.shared.map_links import build_yandex_by_map_url
from src.shared.public_display import format_public_name

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
            SELECT a.id, a.name, a.city_id, a.address, a.latitude, a.longitude, c.name AS city_name,
                   (SELECT MIN(i.price_rental_minor) FROM ice_sessions i
                     WHERE i.arena_id = a.id AND i.price_rental_minor IS NOT NULL
                       AND i.starts_at_utc > NOW()
                       AND i.starts_at_utc < NOW() + make_interval(days => :days)) AS rental_minor,
                   (SELECT i.currency_code FROM ice_sessions i
                     WHERE i.arena_id = a.id AND i.price_rental_minor IS NOT NULL
                       AND i.starts_at_utc > NOW()
                     ORDER BY i.starts_at_utc LIMIT 1) AS rental_currency
            FROM arenas a
            LEFT JOIN cities c ON c.id = a.city_id
            WHERE a.id = ANY(:ids)
              AND COALESCE(a.venue_type, 'ice') = 'ice'
              AND a.merged_into_arena_id IS NULL
            """
        ),
        {"ids": arena_ids, "days": _RENTAL_DAYS},
    )
    out: dict[int, dict[str, Any]] = {}
    for aid, name, arena_city, address, lat, lon, city_name, rental_minor, rental_currency in rows.fetchall():
        label = str(name or "").strip()
        if not label:
            continue
        addr = str(address or "").strip() or None
        venue = ", ".join(p for p in (label, addr, str(city_name or "").strip()) if p)
        out[int(aid)] = {
            "id": int(aid),
            "name": label,
            "city_id": int(arena_city) if arena_city is not None else None,
            "address": addr,
            "map_link": build_yandex_by_map_url({"latitude": lat, "longitude": lon, "address": venue}),
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


async def _primary_arena_ids(session: AsyncSession, trainer_ids: list[int]) -> dict[int, int | None]:
    """``{trainer_id: trainers.primary_arena_id}`` — сырое значение, без исправления."""
    if not trainer_ids:
        return {}
    rows = await session.execute(
        text("SELECT id, primary_arena_id FROM trainers WHERE id = ANY(:ids)"), {"ids": trainer_ids}
    )
    return {int(r[0]): (int(r[1]) if r[1] is not None else None) for r in rows.fetchall()}


async def _profile_city_names(session: AsyncSession, trainer_ids: list[int]) -> dict[int, str | None]:
    """Город профиля, как в ``/client/share-trainer``: ``trainer_profiles.city_id → cities.name``."""
    if not trainer_ids:
        return {}
    rows = await session.execute(
        text(
            """
            SELECT tp.trainer_id, c.name
            FROM trainer_profiles tp
            LEFT JOIN cities c ON c.id = tp.city_id
            WHERE tp.trainer_id = ANY(:ids)
            """
        ),
        {"ids": trainer_ids},
    )
    out: dict[int, str | None] = {}
    for tid, name in rows.fetchall():
        cleaned = str(name).strip() if name is not None else ""
        out[int(tid)] = cleaned or None
    return out


def primary_rink_name(
    primary_arena_id: int | None, arena_ids: list[int], ice_arenas: dict[int, dict[str, Any]]
) -> str | None:
    """Основной каток для плашки (TASK-400): правило ``reconcile_primary_arena`` без записи в БД.

    Основной — ``primary_arena_id``, если он среди площадок тренера, иначе наименьший id площадки.
    Плашка говорит «основной каток», поэтому основной не лёд (зал) — катка нет, другим катком не подменяем.
    """
    ids = [int(a) for a in arena_ids]
    if not ids:
        return None
    primary = primary_arena_id if primary_arena_id in ids else min(ids)
    arena = ice_arenas.get(primary)
    if not arena:
        return None
    return format_public_name(str(arena.get("name") or "")) or None


async def load_showcase_reviews(session: AsyncSession, trainer_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Отзывы всех тренеров выдачи одним запросом (TASK-418).

    Отбор тот же, что у ``site_trainer_page._load_reviews``: подтверждённые, непустой текст,
    новые сверху, не больше ``REVIEWS_SHOWN`` на тренера. Пустой список id — запроса нет.
    """
    from src.application.review_moderation_use_cases import display_name
    from src.application.site_trainer_page import REVIEW_PREVIEW_CHARS, REVIEWS_SHOWN

    ids = [int(tid) for tid in trainer_ids]
    if not ids:
        return {}
    rows = await session.execute(
        text("""
            SELECT trainer_id, rating, review_text, created_at, first_name, last_name
            FROM (
                SELECT r.trainer_id, r.rating, r.review_text, r.created_at, r.id AS rating_id,
                       c.first_name, c.last_name,
                       ROW_NUMBER() OVER (
                           PARTITION BY r.trainer_id
                           ORDER BY r.created_at DESC, r.id DESC
                       ) AS rn
                FROM trainer_ratings r
                LEFT JOIN clients c ON c.telegram_id = r.client_telegram_id
                WHERE r.trainer_id = ANY(:ids)
                  AND r.review_status = 'approved'
                  AND btrim(COALESCE(r.review_text, '')) <> ''
            ) ranked
            WHERE rn <= :lim
            ORDER BY trainer_id, created_at DESC, rating_id DESC
            """),
        {"ids": ids, "lim": REVIEWS_SHOWN},
    )
    out: dict[int, list[dict[str, Any]]] = {}
    for trainer_id, rating, body, created, first, last in rows.fetchall():
        out.setdefault(int(trainer_id), []).append(
            {
                "rating": max(1, min(5, int(rating))),
                "text": str(body).strip()[: REVIEW_PREVIEW_CHARS * 4],
                "date": created.date() if created else None,
                "name": display_name(first, last),
            }
        )
    return out


def showcase_reviews(reviews: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """«Отзывы» единой карточки (TASK-416): то, что ``/t/`` уже отобрал (``_load_reviews``), в JSON.

    Порог тот же, что у сайта (``REVIEWS_MIN_SHOWN``): меньше трёх текстов — ``None``, блока нет,
    оценка остаётся только в герое. Дата — ``YYYY-MM-DD`` (подпись «2 ноября 2026» собирает клиент).
    """
    from src.shared.review_moderation import REVIEWS_MIN_SHOWN

    if len(reviews) < REVIEWS_MIN_SHOWN:
        return None
    return [
        {
            "name": r["name"],
            "rating": int(r["rating"]),
            "text": r["text"],
            "date": r["date"].isoformat() if r.get("date") else None,
        }
        for r in reviews
    ]


def class_photo_urls(trainer: dict[str, Any]) -> list[str]:
    """«На занятиях» (TASK-416): фото тренера после первого — первое уже в герое (``trainer_photo_url``).

    Тот же ключ и тот же URL, что у героя (``file_key_list`` или ``file_key`` через ``b_photo_url``);
    повтор героя и дубли отбрасываем. Пусто — блока нет.
    """
    from src.application.site_trainers import trainer_photo_url
    from src.application.style_b import b_photo_url

    hero = trainer_photo_url(trainer)
    out: list[str] = []
    for photo in (trainer.get("photos") or [])[1:]:
        photo = photo or {}
        url = b_photo_url(photo.get("file_key_list") or photo.get("file_key"))
        if url and url != hero and url not in out:
            out.append(url)
    return out


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
    from src.application.catalog_directions import public_sport_name
    from src.application.site_trainer_catalog import (
        min_price_by_direction,
        services_by_direction,
        window_arena_cities,
        window_in_city,
    )
    from src.application.place_links import public_telegram_cta_url, trainer_start_param
    from src.application.arena_public_use_cases import TRAINER_WINDOWS_LIMIT
    from src.application.site_trainer_page import WEEK_LOOKAHEAD_DAYS, WEEK_WINDOWS_LIMIT, contact_url
    from src.application.site_trainers import trainer_initial, trainer_name, trainer_photo_url
    from src.application.subscription_tier_use_cases import get_trainer_booking_availability
    from src.application.trainer_min_price import enrich_min_session_price
    from src.application.trainer_use_cases import list_active_trainers_for_client
    from src.shared.notification_hours import NOTIFICATION_TZ
    from src.shared.phone_guard import sanitize_public_phone
    from src.shared.config import Settings
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
    # Тот же запас, что у страницы ``/t/``: слот через 8–14 дней (как 19-е у Влада) иначе
    # есть на сайте и пропадает из витрины — диплинк открывает «время заняли».
    windows = (
        await _trainer_windows_on_arena(
            session,
            None,
            bookable,
            timezone_name=NOTIFICATION_TZ,
            limit=WEEK_WINDOWS_LIMIT,
            days=WEEK_LOOKAHEAD_DAYS,
        )
        if bookable
        else {}
    )

    win_cities = await window_arena_cities(session, [w for ws in windows.values() for w in ws])
    # Единая карточка (TASK-400): каток и город. Флаг выключен — ответ прежний, без новых полей.
    unified_card = Settings().unified_trainer_card_enabled
    primary_ids = await _primary_arena_ids(session, ids) if unified_card else {}
    city_names = await _profile_city_names(session, ids) if unified_card else {}
    # Флаг выключен — отзывы не читаем (ни одного запроса). Включён — один ANY(:ids) на всю выдачу.
    reviews_by_trainer = await load_showcase_reviews(session, ids) if unified_card else {}

    out: list[dict[str, Any]] = []
    for t in items:
        tid = int(t["id"])
        profile = t.get("profile") or {}
        name = trainer_name(t)
        contact = contact_url(tid, usernames.get(tid), listed=True)
        # Браузер без initData: выход в Telegram (как «Следующие недели» на /t), не тупик.
        telegram_url = public_telegram_cta_url(
            "", start_param=trainer_start_param(tid), surface="trainer_showcase", city_id=city_id
        )
        out.append(
            {
                "id": tid,
                "name": name,
                "first_name": str(profile.get("first_name") or "").strip() or name,
                "initial": trainer_initial(name),
                "photo_url": trainer_photo_url(t),
                "experience_years": profile.get("experience_years"),
                "description": str(profile.get("description") or "").strip(),
                "education": education_line(profile.get("education")),
                "rating_avg": profile.get("rating_avg"),
                "rating_count": int(profile.get("rating_count") or 0),
                "session_duration_minutes": profile.get("session_duration_minutes"),
                "glide_since": since.get(tid),
                "can_book": can_book[tid],
                "contact_url": contact,
                "telegram_url": telegram_url,
                "phone": sanitize_public_phone(profile.get("phone")),
                "min_session_price_cents": t.get("min_session_price_cents"),
                "min_session_price_currency": t.get("min_session_price_currency"),
                "min_price_by_direction": min_price_by_direction(
                    {"services_by_dir": services_by_direction(t.get("services") or []), "passes": passes.get(tid, [])}
                ),
                "services": [_service_out(s, catalog) for s in t.get("services") or []],
                "arenas": [arenas[a] for a in (t.get("arena_ids") or []) if a in arenas],
                "windows": [
                    {k: w.get(k) for k in ("slot_id", "arena_id", "starts_at", "ends_at", "time", "day")}
                    for w in [
                        w
                        for w in windows.get(tid, [])
                        if window_in_city(w.get("arena_id"), win_cities, city_id)
                    ][:TRAINER_WINDOWS_LIMIT]
                ],
            }
        )
        if unified_card:
            out[-1]["primary_arena_name"] = primary_rink_name(
                primary_ids.get(tid), list(t.get("arena_ids") or []), arenas
            )
            out[-1]["city_name"] = city_names.get(tid)
            # Вид — из вкладок, в БД не пишется. Нет одного вида — null, клиент оставляет названия вкладок.
            out[-1]["sport_name"] = public_sport_name(
                services_by_direction(out[-1]["services"]).keys()
            )
            for arena in out[-1]["arenas"]:
                arena["public_name"] = format_public_name(str(arena.get("name") or "")) or None
            # Отзывы и фото — те же, что на ``/t/`` (TASK-416): подтверждённые тексты, фото после героя.
            out[-1]["reviews"] = showcase_reviews(reviews_by_trainer.get(tid, []))
            out[-1]["class_photos"] = class_photo_urls(t)
    return {"city_id": city_id, "items": out}
