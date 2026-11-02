"""
Publish-first снял ``session_duration_minutes`` и ``min_hours_before_booking`` из обязательных
полей карточки: NULL в этих колонках — нормальное состояние, а не «сломанный профиль».

Тест страхует места, где пустое значение должно молча подменяться продуктовым дефолтом:
если завтра кто-то напишет ``int(profile['session_duration_minutes'])`` без ``or``, запись и
генерация слотов у тренера с незаполненным полем сломаются — и это выйдет наружу, а не в лог.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.api.routes.webapp_client_payloads import serialize_client_booking
from src.application.trainer_hub_first_hours import _trainer_defaults
from src.application.trainer_quick_setup_use_cases import DEFAULT_SESSION_DURATION_MINUTES
from src.application.trainer_use_cases import create_trainer


@pytest.mark.asyncio
async def test_slot_generation_defaults_a_null_session_duration(db_session) -> None:
    """Пресет первых слотов берёт дефолтную длительность, когда поле ещё не заполнено."""
    tid = await create_trainer(db_session, profile={"first_name": "Ноль"})
    await db_session.execute(
        text(
            "UPDATE trainer_profiles SET session_duration_minutes = NULL "
            "WHERE trainer_id = :t"
        ),
        {"t": tid},
    )
    await db_session.commit()

    duration, arena_id = await _trainer_defaults(db_session, tid)
    assert duration == DEFAULT_SESSION_DURATION_MINUTES
    assert arena_id is None


def test_a_booking_payload_defaults_a_null_duration() -> None:
    """Сериализация записи клиента не падает и отдаёт дефолтные 45 минут."""
    payload = serialize_client_booking(
        {
            "id": 1,
            "slot_id": 7,
            "trainer_id": 2,
            "service_id": 3,
            "duration_minutes": None,
        }
    )
    assert payload["duration_minutes"] == 45
