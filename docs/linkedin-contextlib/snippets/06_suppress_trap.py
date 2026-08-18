"""Screenshot 6 of 6 — crop everything above the SNIPPET banner."""

# ── STUBS — not part of the screenshot ──────────────────────────────────────


def rebuild_cache() -> None:
    print("cache rebuilt")


def notify(message: str) -> None:
    print(f"notify: {message}")


# ── SNIPPET ─────────────────────────────────────────────────────────────────

from contextlib import suppress
from pathlib import Path

# ── 6. suppress — a statement of intent, and a trap if you widen it ─────────

cache = Path("/tmp/report.cache")

# Good: one statement, one expected failure, nothing hidden.
with suppress(FileNotFoundError):
    cache.unlink()

# Trap: suppress exits the whole block. When unlink() finds no file,
# the two lines after it never run and nobody hears about it.
with suppress(FileNotFoundError):
    cache.unlink()
    rebuild_cache()  # silently skipped
    notify("cache rebuilt")  # silently skipped

# Fixed: keep the suppression around the risky call only.
with suppress(FileNotFoundError):
    cache.unlink()
rebuild_cache()
notify("cache rebuilt")


# Rule of thumb: suppress is a scalpel for one expected error,
# not a quieter spelling of `except Exception: pass`.
