"""Каток, расписание которого вносят руками раз в неделю (пост в Instagram, фото на двери).

Источника для автоопроса нет: ``extract`` ничего не ищет. Задание нужно, чтобы каток был
«на наблюдении» — пока сеансов нет, карточка зовёт на колокольчик в Telegram, а свежие
сеансы, внесённые вручную, доставляются подписчикам. Пустой прогон витрину не обнуляет.
"""
from __future__ import annotations

from src.ingestion.parsers import IceParser
from src.ingestion.types import Extraction, ParserJob

PARSER_KEY_MANUAL_SCHEDULE = "manual_schedule_v1"


class ManualScheduleParser(IceParser):
    parser_key = PARSER_KEY_MANUAL_SCHEDULE

    async def extract(self, job: ParserJob) -> Extraction:
        return Extraction(arena_id=job.arena_id, parser_key=self.parser_key, snapshot={"source": "manual"}, slots=[])
