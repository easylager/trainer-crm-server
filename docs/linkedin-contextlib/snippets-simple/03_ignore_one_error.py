"""Simple snippet 3 of 4 — the whole file is the screenshot.

Running it prints nothing at all, which is precisely the point of the last block.
"""

from contextlib import suppress
from pathlib import Path

cache = Path("report.cache")

# 3. When one specific error is fine

# The usual way
try:
    cache.unlink()
except FileNotFoundError:
    pass

# With suppress — same behaviour, and it reads as a decision
with suppress(FileNotFoundError):
    cache.unlink()

# Careful: suppress leaves the whole block, not just the failing line
with suppress(FileNotFoundError):
    cache.unlink()
    print("rebuilding cache")  # never runs if unlink() raised
