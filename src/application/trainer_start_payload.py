"""Trainer bot /start payload parsing — extensible registry for deep links."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


START_LINK_PREFIX = "link_"
START_REF_PREFIX = "ref_"
START_JOIN_PAYLOAD = "join"
START_JOIN_REF_PREFIX = "join_ref_"
START_COLLECTIVE_CLAIM_PREFIX = "col_claim_"
START_COLLECTIVE_INVITE_PREFIX = "col_inv_"
START_COLLECTIVE_OPEN_PREFIX = "col_"


class TrainerStartKind(StrEnum):
    LINK = "link"
    REF = "ref"
    JOIN = "join"
    COLLECTIVE_CLAIM = "col_claim"
    COLLECTIVE_INVITE = "col_inv"
    COLLECTIVE_OPEN = "col_open"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedTrainerStart:
    kind: TrainerStartKind
    raw_payload: str
    link_token: str | None = None
    ref_code: str | None = None
    collective_token: str | None = None
    collective_slug: str | None = None


def parse_trainer_start_payload(payload: str | None) -> ParsedTrainerStart:
    raw = (payload or "").strip()
    if not raw:
        return ParsedTrainerStart(kind=TrainerStartKind.EMPTY, raw_payload="")

    if raw.startswith(START_COLLECTIVE_CLAIM_PREFIX):
        token = raw.removeprefix(START_COLLECTIVE_CLAIM_PREFIX).strip()
        return ParsedTrainerStart(
            kind=TrainerStartKind.COLLECTIVE_CLAIM,
            raw_payload=raw,
            collective_token=token or None,
        )

    if raw.startswith(START_COLLECTIVE_INVITE_PREFIX):
        token = raw.removeprefix(START_COLLECTIVE_INVITE_PREFIX).strip()
        return ParsedTrainerStart(
            kind=TrainerStartKind.COLLECTIVE_INVITE,
            raw_payload=raw,
            collective_token=token or None,
        )

    if raw.startswith(START_COLLECTIVE_OPEN_PREFIX):
        slug = raw.removeprefix(START_COLLECTIVE_OPEN_PREFIX).strip()
        return ParsedTrainerStart(
            kind=TrainerStartKind.COLLECTIVE_OPEN,
            raw_payload=raw,
            collective_slug=slug or None,
        )

    if raw == START_JOIN_PAYLOAD:
        return ParsedTrainerStart(kind=TrainerStartKind.JOIN, raw_payload=raw)

    if raw.startswith(START_JOIN_REF_PREFIX):
        ref_code = raw.removeprefix(START_JOIN_REF_PREFIX).split("_")[0]
        return ParsedTrainerStart(
            kind=TrainerStartKind.JOIN,
            raw_payload=raw,
            ref_code=ref_code or None,
        )

    if raw.startswith(START_REF_PREFIX) and not raw.startswith(START_LINK_PREFIX):
        ref_code = raw.removeprefix(START_REF_PREFIX).split("_")[0]
        return ParsedTrainerStart(
            kind=TrainerStartKind.REF,
            raw_payload=raw,
            ref_code=ref_code or None,
        )

    if raw.startswith(START_LINK_PREFIX):
        token = raw.removeprefix(START_LINK_PREFIX)
        ref_code: str | None = None
        if "_ref_" in token:
            parts = token.split("_ref_", 1)
            token = parts[0]
            if len(parts) > 1:
                ref_code = parts[1].split("_")[0] or None
        return ParsedTrainerStart(
            kind=TrainerStartKind.LINK,
            raw_payload=raw,
            link_token=token or None,
            ref_code=ref_code,
        )

    return ParsedTrainerStart(kind=TrainerStartKind.UNKNOWN, raw_payload=raw)
