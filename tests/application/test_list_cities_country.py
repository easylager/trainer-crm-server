"""
TASK-043 follow-up: GET /cities (and any caller of list_cities) exposes `country` so the
frontend can pick the right currency suffix without a second request — see
static/webapp/trainer-profile-main.js `getPriceSuffixForTrainer`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_use_cases import list_cities


async def test_list_cities_includes_country(db_session: AsyncSession) -> None:
    name = f"CountryFieldTest-{uuid.uuid4().hex[:8]}"
    await db_session.execute(
        text(
            "INSERT INTO cities (name, country, price_group) VALUES (:name, 'RU', 'RU_BASE')"
        ),
        {"name": name},
    )
    await db_session.commit()

    cities = await list_cities(db_session)
    match = next((c for c in cities if c["name"] == name), None)
    assert match is not None
    assert match["country"] == "RU"
