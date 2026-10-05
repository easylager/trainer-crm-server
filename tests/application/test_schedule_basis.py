from datetime import datetime, timezone

from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.types import Extraction, ExtractedSlot, ParserJob
from src.shared.schedule_basis import (
    SCHEDULE_BASIS_PHOTO,
    SCHEDULE_BASIS_PROJECTED,
    basis_for_parser_job,
    basis_hint_ru,
)


def test_parser_default_basis_brest_is_projected() -> None:
    assert basis_for_parser_job("brest_lds_v1", {}) == SCHEDULE_BASIS_PROJECTED


def test_normalizer_uses_extraction_basis() -> None:
    job = ParserJob(
        id=1,
        arena_id=22,
        parser_key="brest_lds_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=datetime.now(timezone.utc),
        last_run_at=None,
        config={"timezone": "Europe/Minsk", "default_duration_minutes": 60},
    )
    extraction = Extraction(
        arena_id=22,
        parser_key="brest_lds_v1",
        snapshot="",
        slots=[
            ExtractedSlot(
                local_date="2030-06-01",
                starts_at_local="21:15",
                ends_at_local="22:15",
                kind_raw="open_ice",
            )
        ],
        schedule_basis=SCHEDULE_BASIS_PROJECTED,
    )
    now = datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc)
    drafts = IceSessionNormalizer().normalize(extraction, job, now=now)
    assert len(drafts) == 1
    assert drafts[0].schedule_basis == SCHEDULE_BASIS_PROJECTED


def test_basis_hint_live_is_empty() -> None:
    assert basis_hint_ru("live") is None
    assert basis_hint_ru("projected") == "Обычная сетка катка — уточняйте по телефону"
