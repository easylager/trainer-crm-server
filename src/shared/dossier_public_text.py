"""Strip dossier / loader markers from text shown in the public catalog (TASK-208)."""
from __future__ import annotations

import re
from typing import Any, Mapping

# AC-1 script checks these substrings in public payloads.
DOSSIER_LEAK_NEEDLES: tuple[str, ...] = ("unknown", "Conflicts", "склеивать")

_UNKNOWN_WORD_RE = re.compile(r"\bunknown\b", re.I)
_CONFLICTS_REF_RE = re.compile(
    r"см\.?\s*Conflicts[^.;,\n]*(?:\([^)]*\))?",
    re.I,
)
_SECTION_REF_RE = re.compile(r"см\.?\s*раздел[^.;,\n]*", re.I)
_DO_NOT_MERGE_RE = re.compile(r"\(не\s+склеивать\)", re.I)
_EMPTY_PARENS_RE = re.compile(r"\(\s*\)")
_JUNK_SEP_RE = re.compile(r"[\s;,.·–—-]+$")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")

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


def scrub_dossier_leaks_from_public_text(value: str | None) -> str | None:
    """Remove loader markers; return None if nothing publishable remains."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"", "unknown", "—", "-", "–", "нет"}:
        return None
    text = _UNKNOWN_WORD_RE.sub("", text)
    text = _CONFLICTS_REF_RE.sub("", text)
    text = _SECTION_REF_RE.sub("", text)
    text = _DO_NOT_MERGE_RE.sub("", text)
    text = _EMPTY_PARENS_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = text.strip(" \t;,.·–—-")
    text = _JUNK_SEP_RE.sub("", text).strip()
    if not text or text_contains_dossier_leak(text):
        return None
    return text


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
    has_structure = any(k in out for k in ("daily", "weekly", "hours"))
    if has_structure:
        out.pop("note", None)
    for key in _OPENING_HOURS_STRING_KEYS:
        if key not in out:
            continue
        cleaned = scrub_dossier_leaks_from_public_text(str(out.get(key) or ""))
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
