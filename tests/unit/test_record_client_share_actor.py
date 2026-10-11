"""Выбор actor_hash в record_client_share: явный хэш каталога или дневной хэш тренера."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.application.catalog_consumer_events import CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS
from src.application.client_delight_metrics import record_client_share, share_actor_hash
from src.infrastructure.db.models import CLIENT_SHARE_KIND_PLACE, CLIENT_SHARE_KIND_TRAINER


class _Session:
    def __init__(self) -> None:
        self.params: dict | None = None
        self.commits = 0

    async def execute(self, _stmt, params):
        self.params = params

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_omitted_actor_hash_keeps_trainer_day_hash() -> None:
    session = _Session()
    telegram_id = 555
    await record_client_share(
        session,
        kind=CLIENT_SHARE_KIND_TRAINER,
        telegram_id=telegram_id,
        share_context="catalog",
    )
    expected = share_actor_hash(telegram_id, CLIENT_SHARE_KIND_TRAINER, datetime.now(timezone.utc).date())
    assert session.params is not None
    assert session.params["actor"] == expected
    assert session.commits == 1


@pytest.mark.asyncio
async def test_passed_actor_hash_is_stored_as_is() -> None:
    session = _Session()
    await record_client_share(
        session,
        kind=CLIENT_SHARE_KIND_PLACE,
        telegram_id=42,
        actor_hash="stable-catalog-hash",
    )
    assert session.params is not None
    assert session.params["actor"] == "stable-catalog-hash"
    assert session.params["actor"] != share_actor_hash(42, CLIENT_SHARE_KIND_PLACE, datetime.now(timezone.utc).date())


@pytest.mark.asyncio
async def test_explicit_none_actor_hash_stays_null() -> None:
    """Секрет актёра не задан: каталог передаёт None, дневной хэш по telegram_id не подставляется."""
    session = _Session()
    await record_client_share(
        session,
        kind=CLIENT_SHARE_KIND_PLACE,
        telegram_id=42,
        actor_hash=None,
    )
    assert session.params is not None
    assert session.params["actor"] is None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_excluded_telegram_writes_nothing_even_with_actor_hash() -> None:
    session = _Session()
    staff = next(iter(CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS))
    await record_client_share(
        session,
        kind=CLIENT_SHARE_KIND_PLACE,
        telegram_id=staff,
        actor_hash="stable-catalog-hash",
    )
    assert session.params is None
    assert session.commits == 0
