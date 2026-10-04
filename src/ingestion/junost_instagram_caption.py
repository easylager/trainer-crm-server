"""Junost (arena_id=8): manual Instagram caption — no IG scrape, no junost.by fetch."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from src.ingestion.adapters_minsk_by_egress import (
    _JUNOST_MONTHS,
    _JUNOST_TIME_RANGE,
    _fmt,
    _mk_age_note_when_tiered,
    _minor_to_major,
    _parse_junost_day,
)
from src.ingestion.normalize import parse_price_to_minor
from src.ingestion.parsers import IceParser
from src.ingestion.types import ExtractedSlot, Extraction, ParserJob

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CAPTION_FILE = "data/fixtures/minsk-junost/instagram-caption-latest.txt"

_CAPTION_DATE = re.compile(
    r"(?:понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)?"
    r"\s*(?:\|\s*)?"
    r"(\d{1,2})\s+"
    r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)",
    re.IGNORECASE,
)
_PRICE_ADULT = re.compile(r"взросл\S*\s*[-–—:]?\s*(\d+(?:[,.]\d+)?)\s*р", re.I)
_PRICE_CHILD = re.compile(r"детск\S*\s*[-–—:]?\s*(\d+(?:[,.]\d+)?)\s*р", re.I)
_PRICE_RENTAL = re.compile(r"прокат\s+коньков\s*[-–—:]?\s*(\d+(?:[,.]\d+)?)\s*р", re.I)


def _norm_hhmm(raw: str) -> str:
    parts = raw.strip().split(":")
    return _fmt(int(parts[0]), int(parts[1]))


def _prices_from_caption(plain: str) -> tuple[int | None, int | None, int | None]:
    adult = child = rental = None
    m_adult = _PRICE_ADULT.search(plain)
    m_child = _PRICE_CHILD.search(plain)
    m_rental = _PRICE_RENTAL.search(plain)
    if m_adult:
        adult = parse_price_to_minor(m_adult.group(1).replace(",", ".") + " BYN", already_minor=False)
    if m_child:
        child = parse_price_to_minor(m_child.group(1).replace(",", ".") + " BYN", already_minor=False)
    if m_rental:
        rental = parse_price_to_minor(m_rental.group(1).replace(",", ".") + " BYN", already_minor=False)
    return adult, child, rental


def parse_junost_instagram_caption(
    text: str,
    *,
    pivot_year: int | None = None,
) -> list[ExtractedSlot]:
    """Parse @junost.by post caption (copy-paste). Returns slots without prices set."""
    anchor = pivot_year or date.today().year
    plain = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()
    day_match = _CAPTION_DATE.search(plain)
    if not day_match:
        return []
    local = _parse_junost_day(day_match.group(1), day_match.group(2), pivot_year=anchor)
    if local is None:
        return []
    slots: list[ExtractedSlot] = []
    for time_match in _JUNOST_TIME_RANGE.finditer(plain):
        slots.append(
            ExtractedSlot(
                local_date=local.isoformat(),
                starts_at_local=_norm_hhmm(time_match.group(1)),
                ends_at_local=_norm_hhmm(time_match.group(2)),
                kind_raw="Массовое катание",
                session_label="Главная",
            )
        )
    return slots


def apply_junost_caption_prices(slots: list[ExtractedSlot], caption: str) -> None:
    plain = re.sub(r"\s+", " ", caption.replace("\u00a0", " "))
    adult, child, rental = _prices_from_caption(plain)
    for slot in slots:
        slot.price_adult = _minor_to_major(adult)
        slot.price_child = _minor_to_major(child)
        slot.price_rental = _minor_to_major(rental)
        slot.age_note = _mk_age_note_when_tiered(adult, child)


def load_caption_text(job: ParserJob) -> str:
    config = job.config or {}
    inline = config.get("caption_text")
    if inline and str(inline).strip():
        return str(inline)
    rel = str(config.get("caption_file") or _DEFAULT_CAPTION_FILE)
    path = Path(rel)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.read_text(encoding="utf-8")


class JunostInstagramCaptionParser(IceParser):
    parser_key = "junost_instagram_caption_v1"

    async def extract(self, job: ParserJob) -> Extraction:
        caption = load_caption_text(job)
        pivot = job.config.get("pivot_year")
        pivot_year = int(pivot) if pivot is not None else None
        slots = parse_junost_instagram_caption(caption, pivot_year=pivot_year)
        if slots:
            apply_junost_caption_prices(slots, caption)
        return Extraction(
            arena_id=job.arena_id,
            parser_key=self.parser_key,
            snapshot={
                "source": "instagram_caption_manual",
                "caption_chars": len(caption),
                "slots_parsed": len(slots),
            },
            slots=slots,
        )
