"""TASK-351: источник записи и «Написать в Telegram» — от клика на сайте до строки в БД и среза админа."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.booking_source import (
    BookingSource,
    clean_booking_source,
    get_booking_source_breakdown,
    resolve_booking_source,
    source_from_start_param,
    source_from_via,
)
from src.application.place_links import parse_trainer_deep_link, parse_trainer_start_param, trainer_start_param
from src.application.ice_city_day import city_slug
from src.application.site_trainer_page import trainer_path
from src.infrastructure.db.models import SUBSCRIPTION_TIER_CRM, SUBSCRIPTION_TIER_ONLINE
from tests.api.test_site_trainer_page import _listed
from tests.api.test_webapp_client_miniapp_integration import (
    _create_trainer_online_with_slot,
    _fresh_client_telegram_id,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone

_SECRET = "test-catalog-actor-secret-0123456789abcdef"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", _SECRET)


# ── Коды и метки ─────────────────────────────────────────────────────


def test_start_param_carries_place_without_breaking_old_links() -> None:
    assert trainer_start_param(7, via="p3") == "trainer_7_v_p3"
    assert trainer_start_param(7, via="nope") == "trainer_7"
    assert parse_trainer_start_param("trainer_7_v_c12") == {"trainer_id": 7, "arena_id": None, "slot_id": None, "via": "c12"}
    # Старые разборщики видят того же тренера и каток — экран Mini App не меняется.
    assert parse_trainer_deep_link("trainer_7_v_p3") == (7, None)
    assert parse_trainer_deep_link("trainer_7_a_3") == (7, 3)

    assert source_from_start_param("trainer_7_v_p3") == BookingSource("site_place", arena_id=3)
    assert source_from_start_param("trainer_7_v_c12") == BookingSource("site_city", city_id=12)
    assert source_from_start_param("trainer_7_v_k12") == BookingSource("site_catalog", city_id=12)
    assert source_from_start_param("trainer_7") == BookingSource("site_trainer")
    assert source_from_start_param("trainer_7_a_3") == BookingSource("site_place", arena_id=3)
    assert source_from_start_param("catalog_12_coach") == BookingSource("site_city", city_id=12)
    assert source_from_start_param("arena_42") is None
    assert source_from_start_param("catalog_12") is None
    assert source_from_via("link") == BookingSource("link")
    assert source_from_via("share") == BookingSource("share")
    assert source_from_via("app_button") is None


def test_body_source_is_cleaned_not_trusted() -> None:
    assert clean_booking_source("hacker") is None
    assert clean_booking_source("link", arena_id=5, city_id=1) == BookingSource("link")
    assert clean_booking_source("miniapp", arena_id="5", city_id=-1) == BookingSource("miniapp", arena_id=5)
    # Тело важнее start_param; нет ни того ни другого — «не известно», но запись есть.
    assert resolve_booking_source(body_source="share", signed_start_param="trainer_7") == BookingSource("share")
    assert resolve_booking_source(body_source=None, signed_start_param="trainer_7_v_p3") == BookingSource(
        "site_place", arena_id=3
    )
    assert resolve_booking_source(body_source="bogus", signed_start_param=None) == BookingSource("unknown")


# ── Запись ───────────────────────────────────────────────────────────


async def _book(client, *, slot_id: int, service_id: int, phone: str, extra: dict | None = None, init: str = "mock"):
    return await client.post(
        "/api/webapp/client/booking",
        json={"slot_id": slot_id, "phone": phone, "service_id": service_id, "first_name": "Клиент", **(extra or {})},
        headers={"X-Telegram-Init-Data": init},
    )


async def _booking_source_row(db_session, booking_id: int):
    return (
        await db_session.execute(
            text("SELECT source, source_arena_id, source_city_id FROM bookings WHERE id = :id"), {"id": booking_id}
        )
    ).one()


async def _slot_for_booking(db_session) -> tuple[int, int]:
    _t, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=date.today() + timedelta(days=10), start_hours={18}
    )
    return service_id, slot_id


@pytest.mark.asyncio
async def test_booking_stores_source_from_payload(app_use_test_db, db_session) -> None:
    service_id, slot_id = await _slot_for_booking(db_session)
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    with patch_client_init_auth(ctg):
        async with _client() as client:
            resp = await _book(
                client,
                slot_id=slot_id,
                service_id=service_id,
                phone=phone,
                extra={"source": "site_place", "source_arena_id": 77, "source_city_id": 5},
            )
    assert resp.status_code == 200, resp.text
    assert tuple(await _booking_source_row(db_session, resp.json()["booking_id"])) == ("site_place", 77, 5)


@pytest.mark.asyncio
async def test_old_client_without_source_still_books(app_use_test_db, db_session) -> None:
    """Старый клиент (без поля) и мусор в поле — запись создаётся, источник «не известно»."""
    service_id, slot_id = await _slot_for_booking(db_session)
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    with patch_client_init_auth(ctg):
        async with _client() as client:
            resp = await _book(client, slot_id=slot_id, service_id=service_id, phone=phone, extra={"source": "x" * 300})
    assert resp.status_code == 200, resp.text
    assert tuple(await _booking_source_row(db_session, resp.json()["booking_id"])) == ("unknown", None, None)


@pytest.mark.asyncio
async def test_booking_without_body_source_takes_signed_start_param(app_use_test_db, db_session) -> None:
    """Кэшированный старый JS не шлёт источник — сервер берёт его из подписанной initData."""
    service_id, slot_id = await _slot_for_booking(db_session)
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    with patch_client_init_auth(ctg):
        async with _client() as client:
            resp = await _book(
                client, slot_id=slot_id, service_id=service_id, phone=phone, init="start_param=trainer_5_v_c12&hash=x"
            )
    assert resp.status_code == 200, resp.text
    assert tuple(await _booking_source_row(db_session, resp.json()["booking_id"])) == ("site_city", None, 12)


# ── Сайт: метка места и «Написать» ───────────────────────────────────


@pytest.mark.asyncio
async def test_rink_page_tags_trainer_link_and_trainer_page_passes_it_to_telegram(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_ONLINE)
        place_html = (await client.get(place["path"])).text
        page = (await client.get(f"{trainer_path(tid, name)}?via=p{place['arena_id']}")).text
        plain = (await client.get(trainer_path(tid, name))).text
    # TASK-354: со страницы катка тренеры — через единый блок в каталог (источник «каталог сайта»),
    # не прямыми ссылками; метка ?via=p остаётся для тех, кто пришёл на страницу тренера по ней.
    assert f"/c/{city_slug(place['city_name'])}/trenery?arena={place['arena_id']}" in place_html
    assert f"{trainer_path(tid, name)}?via=p" not in place_html
    assert f"startapp=trainer_{tid}_v_p{place['arena_id']}&amp;surface=trainer_page" in page
    assert f"startapp=trainer_{tid}&amp;surface=trainer_page" in plain
    # Канонический адрес метка не меняет.
    assert f'rel="canonical" href="https://glide.example{trainer_path(tid, name)}"' in page


@pytest.mark.asyncio
async def test_write_click_is_recorded_with_trainer_and_place(app_use_test_db, db_session) -> None:
    async with _client() as client:
        place, tid, name = await _listed(db_session, client, tier=SUBSCRIPTION_TIER_CRM)
        page = (await client.get(f"{trainer_path(tid, name)}?via=p{place['arena_id']}")).text
        beacon = (
            f"/api/public/catalog/contact-click?action=telegram&amp;surface=trainer_page"
            f"&amp;arena_id={place['arena_id']}&amp;trainer_id={tid}&amp;via=p{place['arena_id']}"
        )
        assert f'data-catalog-phone-beacon="{beacon}"' in page and "Написать в Telegram" in page
        assert "a[data-catalog-phone-beacon]" in page
        ua = {"User-Agent": "Mozilla/5.0 (iPhone) Task351"}
        first = await client.post(beacon.replace("&amp;", "&"), headers=ua)
        again = await client.post(beacon.replace("&amp;", "&"), headers=ua)
        direct = await client.post(
            f"/api/public/catalog/contact-click?action=telegram&surface=trainer_page&trainer_id={tid}", headers=ua
        )
        no_trainer = await client.post("/api/public/catalog/contact-click?action=telegram&surface=trainer_page")
    assert (first.status_code, again.status_code, direct.status_code) == (204, 204, 204)
    assert no_trainer.status_code == 400
    rows = (
        await db_session.execute(
            text("""
                SELECT surface, arena_id, city_id, payload
                FROM catalog_consumer_events
                WHERE kind = 'public_contact_click' AND payload->>'trainer_id' = :t
                ORDER BY id
                """),
            {"t": str(tid)},
        )
    ).all()
    # Повтор того же человека за сутки — одна строка; прямой заход на /t/ — своя.
    assert len(rows) == 2
    assert rows[0].surface == "trainer_page"
    assert (rows[0].arena_id, rows[0].city_id) == (place["arena_id"], place["city_id"])
    assert rows[0].payload["action"] == "telegram" and rows[0].payload["source"] == "site_place"
    assert rows[1].payload["source"] == "site_trainer" and rows[1].arena_id is None


# ── Срез ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_breakdown_counts_bookings_and_writes_by_source(app_use_test_db, db_session) -> None:
    now = datetime.now(timezone.utc)
    before = await get_booking_source_breakdown(db_session, as_of=now)
    service_id, slot_id = await _slot_for_booking(db_session)
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    with patch_client_init_auth(ctg):
        async with _client() as client:
            resp = await _book(client, slot_id=slot_id, service_id=service_id, phone=phone, extra={"source": "link"})
    booking_id = resp.json()["booking_id"]
    # Запись трёхнедельной давности — только в 30 днях.
    await db_session.execute(
        text("UPDATE bookings SET created_at = :at WHERE id = :id"), {"at": now - timedelta(days=20), "id": booking_id}
    )
    for days, src in ((1, "site_place"), (2, "site_place"), (12, "site_trainer")):
        await db_session.execute(
            text("""
                INSERT INTO catalog_consumer_events (occurred_at, kind, surface, actor_hash, payload)
                VALUES (:at, 'public_contact_click', 'trainer_page', NULL,
                        CAST(:p AS jsonb))
                """),
            {"at": now - timedelta(days=days), "p": f'{{"action": "telegram", "trainer_id": 1, "source": "{src}"}}'},
        )
    await db_session.commit()
    after = await get_booking_source_breakdown(db_session, as_of=now + timedelta(seconds=1))

    def row(report, code):
        return next(
            (r for r in report["rows"] if r["source"] == code),
            {"bookings_7d": 0, "bookings_30d": 0, "writes_7d": 0, "writes_30d": 0},
        )

    def delta(code, key):
        return row(after, code)[key] - row(before, code)[key]

    assert (delta("link", "bookings_7d"), delta("link", "bookings_30d")) == (0, 1)
    assert (delta("site_place", "writes_7d"), delta("site_place", "writes_30d")) == (2, 2)
    assert (delta("site_trainer", "writes_7d"), delta("site_trainer", "writes_30d")) == (0, 1)
    assert row(after, "link")["label"] == "Ссылка тренера"
    assert after["totals"]["writes_30d"] - before["totals"]["writes_30d"] == 3


@pytest.mark.asyncio
async def test_admin_stats_endpoint_returns_booking_sources(app_use_test_db, db_session) -> None:
    from src.application.stats_use_cases import get_platform_stats

    data = await get_platform_stats(db_session)
    assert data["booking_sources"]["metric"] == "booking_sources"
    assert set(data["booking_sources"]["totals"]) == {"bookings_7d", "bookings_30d", "writes_7d", "writes_30d"}
