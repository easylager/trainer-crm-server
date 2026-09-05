"""Ice parser strategy registry.

Export the public extract → normalize → validate → publish seam.
"""
from src.ingestion.loop import run_ice_ingest_scheduler_loop, run_ice_scrape_ttl_loop
from src.ingestion.parsers import IceParser, MinskArenaSaleframeParser, default_registry
from src.ingestion.scheduler import IceIngestScheduler

__all__ = [
    "IceIngestScheduler",
    "IceParser",
    "MinskArenaSaleframeParser",
    "default_registry",
    "run_ice_ingest_scheduler_loop",
    "run_ice_scrape_ttl_loop",
]
