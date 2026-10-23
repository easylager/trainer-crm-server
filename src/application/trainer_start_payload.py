"""Trainer bot /start payload parsing — extensible registry for deep links."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


START_LINK_PREFIX = "link_"
START_REF_PREFIX = "ref_"
START_JOIN_PAYLOAD = "join"
START_JOIN_REF_PREFIX = "join_ref_"
START_COLLECTIVE_CLAIM_PREFIX = "col_claim_"
START_COLLECTIVE_INVITE_PREFIX = "col_inv_"
START_COLLECTIVE_OPEN_PREFIX = "col_"
# Каток, с которого тренер пришёл (``/join?arena=``): хвост ``link_<token>[_ref_<CODE>]_arena_<id>``.
# Последним — чтобы ``_ref_`` и токен разбирались как раньше.
START_ARENA_SUFFIX = "_arena_"
# Telegram отдаёт боту start-параметр не длиннее 64 символов.
TELEGRAM_START_PAYLOAD_MAX_LEN = 64

_ARENA_SUFFIX_RE = re.compile(r"^(?P<head>.+)" + START_ARENA_SUFFIX + r"(?P<arena>[1-9][0-9]{0,8})$")


def split_arena_suffix(payload: str) -> tuple[str, int | None]:
    """``link_<token>_arena_5`` → (``link_<token>``, 5). Без хвоста — (payload, None).

    Хвост читается только у ``link_``: другие payload-ы катка не несут.
    """
    raw = payload or ""
    if not raw.startswith(START_LINK_PREFIX):
        return raw, None
    m = _ARENA_SUFFIX_RE.match(raw)
    if not m:
        return raw, None
    return m.group("head"), int(m.group("arena"))


def with_arena_suffix(payload: str, arena_id: int | None) -> str:
    """Дописать каток к ``link_`` payload; если не влезает в лимит Telegram — отдать как есть.

    Токен и реферальный код важнее катка: без них тренер не войдёт и реферер не получит бонус.
    """
    if arena_id is None or int(arena_id) <= 0 or not payload.startswith(START_LINK_PREFIX):
        return payload
    out = f"{payload}{START_ARENA_SUFFIX}{int(arena_id)}"
    return out if len(out) <= TELEGRAM_START_PAYLOAD_MAX_LEN else payload


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
    arena_id: int | None = None


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
        without_arena, arena_id = split_arena_suffix(raw)
        token = without_arena.removeprefix(START_LINK_PREFIX)
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
            arena_id=arena_id,
        )

    return ParsedTrainerStart(kind=TrainerStartKind.UNKNOWN, raw_payload=raw)
