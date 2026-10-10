"""Ingestion DB fixtures.

``seed_city_id`` создаёт свой город в транзакции теста: DB-тесты публикации не должны
молча пропускаться (``pytest.skip("need seed cities")``) на пустой CI-базе, где
``cities`` пуста.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


@pytest.fixture
async def seed_city_id(db_session) -> int:
    name = f"Тест-город-{uuid.uuid4().hex[:8]}"
    city_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO cities (name, country, price_group, is_active, sort_order)
                VALUES (:name, 'BY', 'default', true, 0)
                RETURNING id
                """
            ),
            {"name": name},
        )
    ).scalar_one()
    await db_session.flush()
    return int(city_id)
