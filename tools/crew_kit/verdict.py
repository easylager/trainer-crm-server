"""Parse structured reviewer verdict from Crew output."""

from __future__ import annotations

import re

_VERDICT_RE = re.compile(
    r"---CREW_VERDICT---\s*\n\s*status:\s*(PASS|FAIL)\b",
    re.IGNORECASE | re.MULTILINE,
)


def parse_verdict(text: str) -> str | None:
    """Return 'PASS', 'FAIL', or None if missing."""
    if not text:
        return None
    m = _VERDICT_RE.search(text)
    if not m:
        return None
    return m.group(1).upper()
