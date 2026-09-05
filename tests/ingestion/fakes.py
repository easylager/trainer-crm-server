"""Test-only IceParser strategies. Production adapters live in src/ingestion."""
from __future__ import annotations

import json
import re
from typing import Any

from src.ingestion.parsers import IceParser
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob


class FakeJsonWidgetParser(IceParser):
    """Extracts from a saleframe-like JSON blob in job.config['payload']."""

    parser_key = "fake_json_widget_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        payload: dict[str, Any] = job.config["payload"]
        slots: list[ExtractedSlot] = []
        for event in payload.get("events") or []:
            slots.append(
                ExtractedSlot(
                    local_date=str(event["date"]),
                    starts_at_local=str(event["start"]),
                    ends_at_local=event.get("end"),
                    kind_raw=str(event.get("kind") or "Массовое катание"),
                    price_adult=event.get("adult"),
                    price_child=event.get("child"),
                    price_rental=event.get("rental"),
                    source_id=str(event["id"]) if event.get("id") is not None else None,
                    age_note=event.get("age_note"),
                )
            )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=json.dumps(payload, ensure_ascii=False),
            slots=slots,
            observed_at=job.config.get("observed_at"),
        )


class FakeHtmlRowParser(IceParser):
    """Extracts from a single HTML table row in job.config['html']."""

    parser_key = "fake_html_row_v1"
    _ROW = re.compile(
        r'data-kind="([^"]+)"[^>]*>\s*'
        r"<td>(\d{4}-\d{2}-\d{2})</td>\s*"
        r"<td>(\d{2}:\d{2})-(\d{2}:\d{2})</td>\s*"
        r"<td>([^<]*)</td>\s*"
        r"<td>([^<]*)</td>",
        re.IGNORECASE,
    )

    async def extract(self, job: ParserJob) -> Extraction:
        html = str(job.config["html"])
        slots: list[ExtractedSlot] = []
        for match in self._ROW.finditer(html):
            kind_raw, local_date, start, end, adult, child = match.groups()
            slots.append(
                ExtractedSlot(
                    local_date=local_date,
                    starts_at_local=start,
                    ends_at_local=end,
                    kind_raw=kind_raw,
                    price_adult=adult.strip() or None,
                    price_child=child.strip() or None,
                    price_rental=None,
                    source_id="html-1",
                )
            )
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot=html,
            slots=slots,
            observed_at=job.config.get("observed_at"),
        )


class RecordingParser(IceParser):
    """Captures the job.config handed in by the scheduler (AC-002)."""

    parser_key = "recording_v1"

    def __init__(self) -> None:
        self.seen_configs: list[dict[str, Any]] = []

    async def extract(self, job: ParserJob) -> Extraction:
        self.seen_configs.append(dict(job.config))
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={"ok": True},
            slots=[],
        )
