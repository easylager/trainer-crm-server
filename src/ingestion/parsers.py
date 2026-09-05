"""IceParser ABC + registry. Extract only — no ice_sessions writes."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.ingestion.seed_config import PARSER_KEY_MINSK_ARENA
from src.ingestion.types import Extraction, ParserJob


class IceParser(ABC):
    parser_key: str

    @abstractmethod
    async def extract(self, job: ParserJob) -> Extraction:
        """Read the source described by ``job.config``. Do not persist slots."""


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, IceParser] = {}

    def register(self, parser: IceParser) -> None:
        self._parsers[parser.parser_key] = parser

    def get(self, parser_key: str) -> IceParser | None:
        return self._parsers.get(parser_key)


class MinskArenaSaleframeParser(IceParser):
    """Compiling stub. Real ABWS extract is TASK-061."""

    parser_key = PARSER_KEY_MINSK_ARENA

    async def extract(self, job: ParserJob) -> Extraction:
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"stub": True, "parser_key": self.parser_key},
            slots=[],
        )


def default_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(MinskArenaSaleframeParser())
    return registry
