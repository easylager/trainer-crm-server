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
        JunostHtmlParser,
        LedByHtmlParser,
        MinskArenaSaleframeParser,
        MinskSpeedOvalParser,
        ZamokHtmlParser,
    )
    from src.ingestion.adapters_regional_batch_a import (
        BaranovichiLdsParser,
        BrestLdsParser,
        KobrinLdsParser,
        PinskVolnaParser,
    )
    from src.ingestion.adapters_regional_batch_b import (
        GrodnoNemanParser,
        GrodnoTrinitiParser,
        LidaLdsParser,
        NovopolotskLdsParser,
    )
    from src.ingestion.adapters_regional_batch_c import (
        GorkiLdsParser,
        MogilevDsParser,
        OrshaArenaParser,
        OstrovetsLdsParser,
        VitebskDsParser,
    )
    from src.ingestion.adapters_regional_batch_d import (
        BobruiskArenaParser,
        GomelLdsParser,
        ShklovArenaParser,
        SoligorskSzkParser,
    )
    from src.ingestion.adapters_ru_pilot import (
        BalticArenaHtmlParser,
        GrandCanyonIceJsonParser,
        IceburgArenaJsonParser,
        LedovyyDvoretsHtmlParser,
        MagnitArenaHtmlParser,
        OzerkiCalendarParser,
        SokolnikiHtmlParser,
        VtbArenaQticketsParser,
        YubileynyAfishaParser,
    )

    registry = ParserRegistry()
    for parser in (
        MinskArenaSaleframeParser(),
        MinskSpeedOvalParser(),
        ZamokHtmlParser(),
        ChizhovkaHtmlParser(),
        LedByHtmlParser(),
        DiamondHtmlParser(),
        JunostHtmlParser(),
        BrestLdsParser(),
        BaranovichiLdsParser(),
        KobrinLdsParser(),
        PinskVolnaParser(),
        GrodnoTrinitiParser(),
        GrodnoNemanParser(),
        LidaLdsParser(),
        NovopolotskLdsParser(),
        VitebskDsParser(),
        MogilevDsParser(),
        OrshaArenaParser(),
        GorkiLdsParser(),
        OstrovetsLdsParser(),
        BobruiskArenaParser(),
        SoligorskSzkParser(),
        ShklovArenaParser(),
        GomelLdsParser(),
        SokolnikiHtmlParser(),
        LedovyyDvoretsHtmlParser(),
        YubileynyAfishaParser(),
        VtbArenaQticketsParser(),
        BalticArenaHtmlParser(),
        IceburgArenaJsonParser(),
        GrandCanyonIceJsonParser(),
        OzerkiCalendarParser(),
        MagnitArenaHtmlParser(),
    ):
        registry.register(parser)
    return registry


from src.ingestion.adapters import (  # noqa: E402
    ChizhovkaHtmlParser,
    DiamondHtmlParser,
    JunostHtmlParser,
    LedByHtmlParser,
    MinskArenaSaleframeParser,
    MinskSpeedOvalParser,
    ZamokHtmlParser,
)
from src.ingestion.adapters_regional_batch_a import (  # noqa: E402
    BaranovichiLdsParser,
    BrestLdsParser,
    KobrinLdsParser,
    PinskVolnaParser,
)
from src.ingestion.adapters_regional_batch_b import (  # noqa: E402
    GrodnoNemanParser,
    GrodnoTrinitiParser,
    LidaLdsParser,
    NovopolotskLdsParser,
)
from src.ingestion.adapters_regional_batch_c import (  # noqa: E402
    GorkiLdsParser,
    MogilevDsParser,
    OrshaArenaParser,
    OstrovetsLdsParser,
    VitebskDsParser,
)
from src.ingestion.adapters_regional_batch_d import (  # noqa: E402
    BobruiskArenaParser,
    GomelLdsParser,
    ShklovArenaParser,
    SoligorskSzkParser,
)
from src.ingestion.adapters_ru_pilot import (  # noqa: E402
    LedovyyDvoretsHtmlParser,
    SokolnikiHtmlParser,
    VtbArenaQticketsParser,
    YubileynyAfishaParser,
)

__all__ = [
    "BaranovichiLdsParser",
    "BobruiskArenaParser",
    "BrestLdsParser",
    "ChizhovkaHtmlParser",
    "DiamondHtmlParser",
    "GomelLdsParser",
    "GorkiLdsParser",
    "GrodnoNemanParser",
    "GrodnoTrinitiParser",
    "IceParser",
    "JunostHtmlParser",
    "KobrinLdsParser",
    "LedByHtmlParser",
    "LedovyyDvoretsHtmlParser",
    "LidaLdsParser",
    "MinskArenaSaleframeParser",
    "MinskSpeedOvalParser",
    "MogilevDsParser",
    "NovopolotskLdsParser",
    "OrshaArenaParser",
    "OstrovetsLdsParser",
    "ParserRegistry",
    "PinskVolnaParser",
    "ShklovArenaParser",
    "SokolnikiHtmlParser",
    "SoligorskSzkParser",
    "VitebskDsParser",
    "VtbArenaQticketsParser",
    "YubileynyAfishaParser",
    "ZamokHtmlParser",
    "default_registry",
]
