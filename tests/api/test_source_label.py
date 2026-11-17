"""TASK-428 (слой D): метка источника платной ссылки попадает в события и не теряется в дедупе."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth import MiniAppPlatform, MiniAppPrincipal
from src.application.catalog_consumer_events import (
    clean_source_label,
    public_page_view_attribution_payload,
    source_from_start_param,
)
from tests.api.public_page_view_beacon import post_catalog_page_view

SECRET = "l" * 40


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", SECRET)


def test_clean_label() -> None:
    assert clean_source_label("IG_nov-24") == "ig_nov-24"
    for bad in (None, "", "a", "x" * 33, "ig nov", "ig;drop", "<b>"):
        assert clean_source_label(bad) is None
    assert source_from_start_param("src_ig1124") == "ig1124"
    for other in ("arena_12", "catalog_1", "kks_ig", "src_", "src_a", None):
        assert source_from_start_param(other) is None
    assert public_page_view_attribution_payload({"utm_source": "Insta"}) == {"source": "insta"}
    assert public_page_view_attribution_payload({"utm_source": "bad label"}) == {}


async def _payloads(db, kind: str) -> list[dict]:
    rows = await db.execute(
        text("SELECT payload FROM catalog_consumer_events WHERE kind = :k ORDER BY id"), {"k": kind}
    )
    return [r[0] for r in rows.all()]


@pytest.mark.asyncio
async def test_site_page_view_keeps_ad_visit_after_organic(app_use_test_db, db_session) -> None:
    ua = {"user-agent": "Mozilla/5.0 (iPhone) Safari"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        for extra in (None, {"utm_source": "instagram"}, {"utm_source": "instagram"}):
            r = await post_catalog_page_view(client, surface="catalog_home", path="/", extra_params=extra, headers=ua)
            assert r.status_code == 204
    sources = [p.get("source") for p in await _payloads(db_session, "public_page_view")]
    assert sources == [None, "instagram"]  # органика не съела рекламу, повтор рекламы — дедуп


@pytest.mark.asyncio
async def test_miniapp_entry_with_src_label(app_use_test_db, db_session) -> None:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=9428777)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
            for sp in (None, "src_ig1124"):
                r = await client.post(
                    "/api/webapp/client/catalog/presence",
                    json={"surface": "miniapp_shell", "start_param": sp},
                    headers={"X-Telegram-Init-Data": "mock"},
                )
                assert r.json()["recorded"] is True
    payloads = await _payloads(db_session, "miniapp_catalog_entry")
    assert [p.get("source") for p in payloads] == [None, "ig1124"]


@pytest.mark.asyncio
async def test_long_label_is_ignored_not_rejected(app_use_test_db, db_session) -> None:
    """Ревью п. 8: слишком длинная метка не роняет просмотр (не 422) — просмотр пишется без метки."""
    ua = {"user-agent": "Mozilla/5.0 (iPhone) Safari"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        r = await post_catalog_page_view(
            client, surface="catalog_home", path="/", extra_params={"utm_source": "x" * 300}, headers=ua
        )
    assert r.status_code == 204
    assert [p.get("source") for p in await _payloads(db_session, "public_page_view")] == [None]


@pytest.mark.asyncio
async def test_distinct_labels_per_person_day_are_capped(app_use_test_db, db_session) -> None:
    """Ревью п. 8: перебор меток не раздувает таблицу — не больше трёх разных меток на человека в сутки."""
    from src.application.catalog_consumer_events import MAX_SOURCES_PER_DAY

    ua = {"user-agent": "Mozilla/5.0 (Android) Chrome"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        for i in range(MAX_SOURCES_PER_DAY + 3):
            await post_catalog_page_view(
                client, surface="catalog_home", path="/", extra_params={"utm_source": f"label{i}"}, headers=ua
            )
    sources = [p.get("source") for p in await _payloads(db_session, "public_page_view")]
    assert sources == [f"label{i}" for i in range(MAX_SOURCES_PER_DAY)] + [None]
