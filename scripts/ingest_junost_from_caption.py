"""Publish Junost MK slots from an Instagram post caption (copy-paste, no IG API).

Usage:
  PYTHONPATH=. python scripts/ingest_junost_from_caption.py --file post.txt
  PYTHONPATH=. python scripts/ingest_junost_from_caption.py --file post.txt --write-latest
  PYTHONPATH=. python scripts/ingest_junost_from_caption.py --file post.txt --i-know-this-is-prod

Prod DB (from Mac):
  PUB="$(railway run -s Postgres-W--1 -- printenv DATABASE_PUBLIC_URL)"
  export DATABASE_URL="postgresql+asyncpg://${PUB#postgresql://}"
  PYTHONPATH=. .venv/bin/python scripts/ingest_junost_from_caption.py --file post.txt \\
    --write-latest --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.config import Settings
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    warn_prod_ack,
)

LATEST_CAPTION = ROOT / "data/fixtures/minsk-junost/instagram-caption-latest.txt"
PARSER_KEY = "junost_instagram_caption_v1"
ARENA_ID = 8


def _default_job_config() -> dict:
    return {
        "caption_file": "data/fixtures/minsk-junost/instagram-caption-latest.txt",
        "timezone": "Europe/Minsk",
        "kind": "public_skate",
        "requires_by_egress": False,
        "source_label": "instagram_caption_manual",
    }


async def _run(caption: str, *, dry_run: bool) -> None:
    from sqlalchemy import text

    from src.infrastructure.db.session import async_session_factory
    from src.ingestion.junost_instagram_caption import JunostInstagramCaptionParser
    from src.ingestion.normalize import IceSessionNormalizer
    from src.ingestion.publish import SqlAlchemyIceSessionPublisher
    from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
    from src.ingestion.types import RUN_STATUS_OK, ParserJob, ScrapeRunRecord
    from src.ingestion.validate import IceSessionValidator

    now = datetime.now(timezone.utc)
    parser = JunostInstagramCaptionParser()
    job = ParserJob(
        id=0,
        arena_id=ARENA_ID,
        parser_key=PARSER_KEY,
        is_enabled=True,
        cadence="weekly",
        next_run_at=now,
        last_run_at=None,
        config={**_default_job_config(), "caption_text": caption},
    )

    extraction = await parser.extract(job)
    normalizer = IceSessionNormalizer()
    drafts = normalizer.normalize(extraction, job, now=now)
    validated = IceSessionValidator().validate(drafts)

    print(f"parsed={len(extraction.slots)} future_slots={len(validated)}")
    if not validated:
        print("nothing to publish (check dates in caption vs today)")
        return
    for draft in validated:
        print(
            f"  {draft.local_date} {draft.starts_at_local}-{draft.ends_at_local} "
            f"adult={draft.price_adult_minor} child={draft.price_child_minor} "
            f"rental={draft.price_rental_minor}"
        )
    if dry_run:
        print("dry-run; pass --apply to write ice_sessions")
        return

    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT id, parser_key, config
                    FROM ice_parser_jobs
                    WHERE arena_id = :arena_id
                    """
                ),
                {"arena_id": ARENA_ID},
            )
        ).first()
        job_id = int(row[0]) if row else 0
        if row and str(row[1]) != PARSER_KEY:
            print(f"WARNING: ice_parser_jobs.parser_key={row[1]!r} — run seed to switch to {PARSER_KEY}")

        record = ScrapeRunRecord(
            job_id=job_id,
            arena_id=ARENA_ID,
            parser_key=PARSER_KEY,
            status=RUN_STATUS_OK,
            slot_count=len(validated),
            slots_dropped=max(0, len(extraction.slots) - len(validated)),
            error_message=None,
            started_at=now,
            finished_at=now,
            snapshot=extraction.snapshot,
        )
        recorder = SqlAlchemyScrapeRunRecorder(session)
        run_id = await recorder.record(record)
        publisher = SqlAlchemyIceSessionPublisher(session)
        published = await publisher.publish(record, validated, run_id=run_id)
        if row:
            await session.execute(
                text(
                    """
                    UPDATE ice_parser_jobs
                    SET parser_key = :parser_key,
                        is_enabled = true,
                        config = CAST(:config AS jsonb),
                        last_run_at = :now,
                        next_run_at = :now
                    WHERE arena_id = :arena_id
                    """
                ),
                {
                    "parser_key": PARSER_KEY,
                    "config": json.dumps({**_default_job_config(), "caption_text": caption}),
                    "now": now,
                    "arena_id": ARENA_ID,
                },
            )
        await session.commit()
        print(f"status=ok slots_published={published} run_id={run_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True, help="caption text file (UTF-8)")
    parser.add_argument(
        "--write-latest",
        action="store_true",
        help=f"also copy caption to {LATEST_CAPTION.relative_to(ROOT)}",
    )
    parser.add_argument("--apply", action="store_true", help="write to database (default: dry-run)")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()

    caption = args.file.read_text(encoding="utf-8").strip()
    if not caption:
        raise SystemExit("caption file is empty")

    if args.write_latest:
        LATEST_CAPTION.parent.mkdir(parents=True, exist_ok=True)
        LATEST_CAPTION.write_text(caption + "\n", encoding="utf-8")
        print(f"wrote {LATEST_CAPTION}")

    apply = args.apply
    if apply:
        url = Settings().database_url
        assert_database_url(url, apply=True, allow_prod=args.i_know_this_is_prod)
        if args.i_know_this_is_prod:
            assert_railway_target_database(url)
            warn_prod_ack()

    asyncio.run(_run(caption, dry_run=not apply))


if __name__ == "__main__":
    main()
