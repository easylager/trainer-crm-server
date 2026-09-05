"""Ice parser strategy registry.

Export the public extract → normalize → validate seam. Publication is TASK-061.
"""
from src.ingestion.loop import run_ice_ingest_scheduler_loop
from src.ingestion.parsers import IceParser, MinskArenaSaleframeParser, default_registry
from src.ingestion.scheduler import IceIngestScheduler

__all__ = [
    "IceIngestScheduler",
    "IceParser",
    "MinskArenaSaleframeParser",
    "default_registry",
    "run_ice_ingest_scheduler_loop",
]
