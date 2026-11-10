"""У каждого города с катком или тренером есть предложный падеж.

Список — города из базы, у которых есть каток или тренер. Запрос в тесте ловит
новый город в той базе, на которой запущен pytest.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from src.shared.city_locative import city_locative

# Города, которые тесты создают сами («Плейсск abcdef»). Это не каталог.
_FIXTURE_CITY = re.compile(r"^(?:Плейсск|Катковск|День|Скрин) ")

# Снято с базы: DISTINCT cities, у которых есть арена или строка trainer_cities.
CITIES_WITH_A_RINK_OR_TRAINER = (
    "Барановичи",
    "Береза",
    "Бобруйск",
    "Брест",
    "Витебск",
    "Гомель",
    "Горки",
    "Гродно",
    "Жодино",
    "Ивацевичи",
    "Кобрин",
    "Лида",
    "Лунинец",
    "Минск",
    "Могилёв",
    "Мозырь",
    "Молодечно",
    "Москва/МО",
    "Новополоцк",
    "Орша",
    "Островец",
    "Пинск",
    "Пружаны",
    "Раубичи",
    "Санкт-Петербург/ЛО",
    "Силичи",
    "Солигорск",
    "Шклов",
    "Новолукомль",
)

_SQL = """
SELECT DISTINCT c.name
FROM cities c
WHERE EXISTS (
    SELECT 1 FROM arenas a
    WHERE a.city_id = c.id AND a.merged_into_arena_id IS NULL
) OR EXISTS (
    SELECT 1 FROM trainer_cities tc WHERE tc.city_id = c.id
)
"""


@pytest.mark.parametrize("name", CITIES_WITH_A_RINK_OR_TRAINER)
def test_city_from_the_catalog_database_has_a_locative(name: str) -> None:
    assert city_locative(name)


@pytest.mark.asyncio
async def test_every_database_city_with_a_rink_or_trainer_has_a_locative(db_session) -> None:
    rows = (await db_session.execute(text(_SQL))).all()
    missing = [name for (name,) in rows if not _FIXTURE_CITY.match(name) and not city_locative(name)]
    assert missing == []
