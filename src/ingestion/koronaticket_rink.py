"""Parse Korona Ticket rink SSR (window.__NUXT__) for Zamok remaining seats."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.ingestion.source_io import fetch_http_text_optional
from src.ingestion.types import ExtractedSlot, ParserJob

_DEFAULT_RINK_URL = "https://koronaticket.by/rink"
_NUXT_MARKER = "window.__NUXT__=(function("
_SESSION = re.compile(
    r'start_at:"(?P<start>\d{4}-\d{2}-\d{2}T\d{2}:\d{2})"'
    r',end_at:"(?P<end>\d{4}-\d{2}-\d{2}T\d{2}:\d{2})"'
    r",is_available:(?P<avail>[^,]+),"
    r".*?"
    r"tickets_info:\{count:(?P<count>[^,]+),locked:(?P<locked>[^,]+),"
    r"ordered:(?P<ordered>[^,]+),bought:(?P<bought>[^}]+)\}",
    re.S,
)
_CAPACITY_NOTE_MAX = 128
_KORONA_FIXTURE = "korona-rink.html"


@dataclass(frozen=True)
class KoronaRinkSession:
    local_date: date
    starts_at_local: str
    ends_at_local: str
    remaining: int
    is_available: bool


def remaining_seats(count: int, bought: int, locked: int, ordered: int) -> int:
    """Same net capacity Korona shows on session chips (count − sold − holds)."""
    return max(0, int(count) - int(bought) - int(locked) - int(ordered))


def format_capacity_note(remaining: int) -> str:
    if remaining <= 0:
        return "нет мест"
    return f"{remaining} мест"


def parse_rink_nuxt_html(html: str) -> list[KoronaRinkSession]:
    chunk = _nuxt_chunks(html)
    if chunk is None:
        return []
    param_names, body, args_raw = chunk
    try:
        args = json.loads(f"[{_js_args_to_json(args_raw)}]")
    except json.JSONDecodeError:
        return []
    if len(param_names) != len(args):
        return []
    scope: dict[str, Any] = dict(zip(param_names, args, strict=True))
    sessions: list[KoronaRinkSession] = []
    for block in _SESSION.finditer(body):
        start = block.group("start")
        end = block.group("end")
        local_date = date.fromisoformat(start[:10])
        starts_at_local = start[11:16]
        ends_at_local = end[11:16]
        count = _resolve_num(block.group("count"), scope)
        locked = _resolve_num(block.group("locked"), scope)
        ordered = _resolve_num(block.group("ordered"), scope)
        bought = _resolve_num(block.group("bought"), scope)
        if count is None or bought is None or locked is None or ordered is None:
            continue
        avail_raw = block.group("avail").strip()
        is_available = _resolve_bool(avail_raw, scope)
        remaining = remaining_seats(count, bought, locked, ordered)
        sessions.append(
            KoronaRinkSession(
                local_date=local_date,
                starts_at_local=starts_at_local,
                ends_at_local=ends_at_local,
                remaining=remaining,
                is_available=is_available,
            )
        )
    return sessions


def _nuxt_chunks(html: str) -> tuple[list[str], str, str] | None:
    start = html.find(_NUXT_MARKER)
    if start < 0:
        return None
    cursor = start + len(_NUXT_MARKER)
    params_end = html.find(")", cursor)
    if params_end < 0:
        return None
    param_names = [p.strip() for p in html[cursor:params_end].split(",") if p.strip()]
    body_start = html.find("{", params_end)
    if body_start < 0:
        return None
    body_start += 1
    suffix = html[body_start:]
    invoke_idx = suffix.rfind("}(")
    if invoke_idx < 0:
        return None
    body = suffix[:invoke_idx]
    rest = suffix[invoke_idx + 2 :]
    close = rest.rfind("));")
    if close < 0:
        return None
    return param_names, body, rest[:close]


def enrich_zamok_slots(slots: list[ExtractedSlot], korona_html: str) -> int:
    """Fill capacity_note on slots matched by (local_date, starts_at_local). Returns match count."""
    by_key: dict[tuple[str, str], KoronaRinkSession] = {}
    for session in parse_rink_nuxt_html(korona_html):
        by_key[(session.local_date.isoformat(), session.starts_at_local)] = session
    matched = 0
    for slot in slots:
        local = slot.local_date.isoformat() if isinstance(slot.local_date, date) else str(slot.local_date)[:10]
        start = str(slot.starts_at_local)
        if len(start) > 5:
            start = start[:5]
        korona = by_key.get((local, start))
        if korona is None:
            continue
        note = format_capacity_note(korona.remaining)
        if len(note) > _CAPACITY_NOTE_MAX:
            note = note[: _CAPACITY_NOTE_MAX - 1] + "…"
        slot.capacity_note = note
        matched += 1
    return matched


async def load_korona_rink_html(job: ParserJob) -> str | None:
    fixture_dir = job.config.get("fixture_dir")
    if fixture_dir:
        path = Path(str(fixture_dir)) / _KORONA_FIXTURE
        if path.is_file():
            return path.read_text(encoding="utf-8")
    url = str(job.config.get("korona_tickets_url") or _DEFAULT_RINK_URL)
    return await fetch_http_text_optional(url)


def _resolve_num(token: str, scope: dict[str, Any]) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token in scope:
        value = scope[token]
        if isinstance(value, bool) or value is None:
            return None
        return int(value)
    try:
        return int(token)
    except ValueError:
        return None


def _resolve_bool(token: str, scope: dict[str, Any]) -> bool:
    token = token.strip()
    if token in scope:
        value = scope[token]
        if isinstance(value, bool):
            return value
        return bool(value)
    if token == "true":
        return True
    if token == "false":
        return False
    return False


def _js_args_to_json(raw: str) -> str:
    """Best-effort: Nuxt IIFE tail uses JSON-compatible literals."""
    out: list[str] = []
    cur = ""
    depth = 0
    in_str = False
    esc = False
    for ch in raw:
        if in_str:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur += ch
            continue
        if ch == "," and depth == 0:
            out.append(_js_literal_to_json(cur.strip()))
            cur = ""
            continue
        cur += ch
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
    if cur.strip():
        out.append(_js_literal_to_json(cur.strip()))
    return ",".join(out)


def _js_literal_to_json(token: str) -> str:
    if token in {"true", "false", "null"}:
        return token
    if token.startswith('"'):
        return token
    return token
