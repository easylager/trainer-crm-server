"""
Shared JSON builders for client Mini App: bookings by day, requests list.

Kept separate from webapp.py so trainer-edges and other routers can reuse
``client_bookings_days_payload`` without import cycles.
"""
from __future__ import annotations

from itertools import groupby

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import list_bookings_for_client
from src.application.client_request_use_cases import list_my_requests_with_responses
from src.shared.price_tier_kind import normalize_price_tier_kind, price_tier_label_ru

CLIENT_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def serialize_client_booking(b: dict) -> dict:
    """Client booking to JSON: date/time strings, arena, service, optional tier snapshot."""
    slot_date = b.get("slot_date")
    start_time = b.get("start_time")
    end_time = b.get("end_time")
    ptk = normalize_price_tier_kind(b.get("price_tier_kind"))
    svc_name = (b.get("service_name") or "").strip()
    pc = b.get("price_cents")
    return {
        "id": b["id"],
        "slot_id": b.get("slot_id"),
        "trainer_id": b.get("trainer_id"),
        "service_id": b.get("service_id"),
        "service_name": svc_name or None,
        "price_tier_kind": ptk,
        "price_tier_label": price_tier_label_ru(ptk) if ptk else None,
        "trainer_name": (b.get("trainer_name") or "Тренер").strip(),
        "trainer_telegram_id": b.get("trainer_telegram_id"),
        "trainer_telegram_username": (b.get("trainer_telegram_username") or "").strip() or None,
        "trainer_phone": (b.get("trainer_phone") or "").strip() or None,
        "slot_date": slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date),
        "start_time": start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time)[:5],
        "end_time": end_time.strftime("%H:%M") if hasattr(end_time, "strftime") else str(end_time)[:5],
        "duration_minutes": b.get("duration_minutes") or 45,
        "status": (b.get("status") or "pending").strip(),
        "place_display": b.get("place_display") or "Уточните у тренера",
        "arena_name": b.get("arena_name"),
        "arena_address": b.get("arena_address"),
        "map_link": b.get("map_link"),
        "price_cents": int(pc) if pc is not None else None,
        "service_client_notice": (
            (b.get("service_client_notice") or "").strip() or None
        ),
        "hub_in_session": bool(b.get("hub_in_session")),
        "arena_id": b.get("arena_id"),
        "service_price_variant_id": b.get("service_price_variant_id"),
        "trainer_city_id": b.get("trainer_city_id"),
    }


def serialize_client_request(req: dict) -> dict:
    """Request + responses to JSON-safe (created_at as string)."""
    created_at = req.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    elif created_at is not None:
        created_at = str(created_at)
    return {
        "id": req["id"],
        "city_id": req["city_id"],
        "service_id": req["service_id"],
        "comment": req.get("comment"),
        "created_at": created_at,
        "status": req.get("status"),
        "city_name": req.get("city_name"),
        "service_name": req.get("service_name"),
        "responses": [
            {
                "trainer_id": r.get("trainer_id"),
                "name": r.get("name"),
                "telegram_id": r.get("telegram_id"),
                "telegram_username": r.get("telegram_username"),
                "trainer_comment": r.get("trainer_comment"),
                "rating_avg": r.get("rating_avg"),
                "rating_count": r.get("rating_count") or 0,
                "experience_years": r.get("experience_years"),
                "description": r.get("description"),
                "education": r.get("education"),
                "education_entries": r.get("education_entries") or [],
                "session_duration_minutes": r.get("session_duration_minutes"),
                "photo_key": r.get("photo_key"),
                "services": r.get("services") or [],
                "arena_names": r.get("arena_names") or [],
                "arena_ids": r.get("arena_ids") or [],
                "primary_arena_id": r.get("primary_arena_id"),
            }
            for r in (req.get("responses") or [])
        ],
    }


async def client_bookings_days_payload(session: AsyncSession, telegram_id: int) -> dict:
    """Shared JSON body for GET /client/bookings, trainer-edges, and client hub bootstrap."""
    bookings = await list_bookings_for_client(session, telegram_id)
    if not bookings:
        return {"days": []}

    days_list = []
    for slot_date, group in groupby(bookings, key=lambda b: b["slot_date"]):
        day_bookings = list(group)
        date_str = slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date)
        dow = slot_date.weekday() if hasattr(slot_date, "weekday") else 0
        day_label = CLIENT_DAYS[dow] if dow < len(CLIENT_DAYS) else ""
        days_list.append({
            "date": date_str,
            "day_label": day_label,
            "bookings": [serialize_client_booking(b) for b in day_bookings],
        })
    return {"days": days_list}


async def client_requests_list_payload(session: AsyncSession, telegram_id: int) -> dict:
    """Shared JSON body for GET /client/requests and client hub bootstrap."""
    items = await list_my_requests_with_responses(session, telegram_id)
    return {"items": [serialize_client_request(r) for r in items]}
