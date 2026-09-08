"""IceParser ABC + registry. Extract only — no ice_sessions writes."""
from __future__ import annotations

from abc import ABC, abstractmethod

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


def default_registry() -> ParserRegistry:
    from src.ingestion.adapters import (
        ChizhovkaHtmlParser,
        DiamondHtmlParser,
        LedByHtmlParser,
        MinskArenaSaleframeParser,
        MinskSpeedOvalParser,
        ZamokHtmlParser,
    )

    registry = ParserRegistry()
    for parser in (
        MinskArenaSaleframeParser(),
        MinskSpeedOvalParser(),
        ZamokHtmlParser(),
        ChizhovkaHtmlParser(),
        LedByHtmlParser(),
        DiamondHtmlParser(),
    ):
        registry.register(parser)
    return registry


from src.ingestion.adapters import (  # noqa: E402
    ChizhovkaHtmlParser,
    DiamondHtmlParser,
    LedByHtmlParser,
    MinskArenaSaleframeParser,
    MinskSpeedOvalParser,
    ZamokHtmlParser,
)

__all__ = [
    "ChizhovkaHtmlParser",
    "DiamondHtmlParser",
    "IceParser",
    "LedByHtmlParser",
    "MinskArenaSaleframeParser",
    "MinskSpeedOvalParser",
    "ParserRegistry",
    "ZamokHtmlParser",
    "default_registry",
]
