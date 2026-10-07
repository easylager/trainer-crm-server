"""Strip dossier / loader markers from text shown in the public catalog (TASK-208)."""
from __future__ import annotations

import re
from typing import Any, Mapping

# AC-1 script checks these substrings in public payloads.
DOSSIER_LEAK_NEEDLES: tuple[str, ...] = ("unknown", "Conflicts", "склеивать")

# Clause ends at «;» or at a sentence dot (not «16:45» and not «т.ч.»).
_CLAUSE_DELIM_RE = re.compile(r"\s*;\s*|(?<![0-9A-Za-zА-Яа-яЁё])\.(?!\d)\s*|(?<=\d)\.(?!\d)\s*")
_LEAK_RE = re.compile(r"\bunknown\b|conflicts|склеивать|см\.", re.I)
_SLASH_LABEL_RE = re.compile(r"^(\S+)\s*/\s*\S+\s*:\s*")
_SPACED_DASH_RE = re.compile(r"\s+[—–-]\s+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")
_LABEL_WORD_RE = re.compile(r"^(?:комплекс|касс[аы]|каток|ежедневно|катания)$", re.I)
_STRUCTURE_KEYS = ("daily", "kassa", "complex", "hours")

_OPENING_HOURS_STRING_KEYS = ("note", "access_note", "rental_close", "track_close")


def text_contains_dossier_leak(value: str | None) -> bool:
    if not value:
        return False
    hay = str(value)
    low = hay.casefold()
    if "unknown" in low:
        return True
    if "conflicts" in low:
        return True
    if "склеивать" in low:
        return True
    return False


def _split_clauses(text: str) -> list[str]:
    return [part.strip(" \t") for part in _CLAUSE_DELIM_RE.split(text) if part.strip(" \t.;")]


def _collapse_slash_label(text: str) -> str:
    """«администрация / справочная: …» → «Администрация: …»."""
    match = _SLASH_LABEL_RE.match(text)
    if not match:
        return text
    word = match.group(1)
    label = word[:1].upper() + word[1:]
    return f"{label}: {text[match.end():].lstrip()}"


def scrub_dossier_leaks_from_public_text(value: str | None) -> str | None:
    """Drop each clause that contains a dossier marker, not only the marker word."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"", "unknown", "—", "-", "–", "нет"}:
        return None
    if not _LEAK_RE.search(text):
        return text
    kept = [clause for clause in _split_clauses(text) if not _LEAK_RE.search(clause)]
    if not kept:
        return None
    cleaned = _collapse_slash_label(". ".join(kept))
    cleaned = cleaned.strip(" \t;,.·–—-")
    if not cleaned or text_contains_dossier_leak(cleaned):
        return None
    return cleaned


def _hhmm_forms(hhmm: str) -> set[str]:
    hours, minutes = hhmm.split(":")
    return {f"{int(hours)}:{minutes}", f"{int(hours):02d}:{minutes}"}


def _structure_intervals(hours: Mapping[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for key in _STRUCTURE_KEYS:
        block = hours.get(key)
        if not isinstance(block, Mapping):
            continue
        open_ = str(block.get("open") or "")
        close = str(block.get("close") or "")
        if re.fullmatch(r"\d{2}:\d{2}", open_) and re.fullmatch(r"\d{2}:\d{2}", close):
            found.append((open_, close))
    return found


def _strip_known_interval(clause: str, open_: str, close: str) -> tuple[str, bool]:
    text = clause
    hit = False
    for left in _hhmm_forms(open_):
        for right in _hhmm_forms(close):
            pattern = re.compile(rf"{re.escape(left)}\s*[–—-]\s*{re.escape(right)}")
            text, count = pattern.subn("", text)
            hit = hit or count > 0
    return text, hit


def _label_only(fragment: str) -> bool:
    words = re.findall(r"[A-Za-zА-Яа-яЁё]+", fragment)
    return not words or all(_LABEL_WORD_RE.fullmatch(word) for word in words)


def _drop_structure_echo(note: str, hours: Mapping[str, Any]) -> str | None:
    """Drop clauses that only repeat kassa/complex/daily; trim a repeated interval."""
    intervals = _structure_intervals(hours)
    if not intervals:
        return note
    kept: list[str] = []
    for clause in _split_clauses(note):
        text = clause
        echoed = False
        for open_, close in intervals:
            text, hit = _strip_known_interval(text, open_, close)
            echoed = echoed or hit
        text = _SPACED_DASH_RE.sub(" ", text)
        text = _MULTI_SPACE_RE.sub(" ", text).strip(" \t,;:.—–-")
        if echoed and _label_only(text):
            continue
        if text:
            kept.append(text)
    if not kept:
        return None
    return ". ".join(kept)


def opening_hours_public_note(raw: str | None, hours: Mapping[str, Any] | None) -> str | None:
    cleaned = scrub_dossier_leaks_from_public_text(raw)
    if not cleaned:
        return None
    return _drop_structure_echo(cleaned, hours or {})


def sanitize_public_district(value: str | None) -> str | None:
    cleaned = scrub_dossier_leaks_from_public_text(value)
    if cleaned is None:
        return None
    if cleaned.casefold() == "unknown":
        return None
    return cleaned


def sanitize_opening_hours_for_public(hours: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(hours, Mapping) or not hours:
        return None
    out: dict[str, Any] = dict(hours)
    for key in _OPENING_HOURS_STRING_KEYS:
        if key not in out:
            continue
        raw = str(out.get(key) or "")
        cleaned = (
            opening_hours_public_note(raw, out)
            if key == "note"
            else scrub_dossier_leaks_from_public_text(raw)
        )
        if cleaned:
            out[key] = cleaned
        else:
            out.pop(key, None)
    if not out:
        return None
    return out


def public_payload_contains_dossier_leak(payload: Mapping[str, Any]) -> list[str]:
    """Return human-readable paths where a leak needle appears (for check scripts)."""
    hits: list[str] = []

    def walk(obj: Any, prefix: str) -> None:
        if isinstance(obj, str):
            for needle in DOSSIER_LEAK_NEEDLES:
                if needle.casefold() in obj.casefold():
                    hits.append(f"{prefix}: …{needle}…")
            return
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}" if prefix else str(k))
            return
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{prefix}[{i}]")

    walk(payload, "")
    return hits
