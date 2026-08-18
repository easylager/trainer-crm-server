"""Simple snippet 1 of 4 — crop everything above the SNIPPET banner."""

# ── STUBS — not part of the screenshot ──────────────────────────────────────

import os
import tempfile

os.chdir(tempfile.mkdtemp())
for _name in ("a.txt", "b.txt", "c.txt"):
    with open(_name, "w", encoding="utf-8") as _fh:
        _fh.write(f"contents of {_name}\n")

# ── SNIPPET ─────────────────────────────────────────────────────────────────

from contextlib import ExitStack

# 1. Several files, one with-block

# The usual way — fine, but only if you know the number in advance
with open("a.txt") as a, open("b.txt") as b:
    print(a.read(), b.read())

# With ExitStack — any number, all closed on the way out
paths = ["a.txt", "b.txt", "c.txt"]

with ExitStack() as stack:
    # 2. Open all files
    files = [stack.enter_context(open(p)) for p in paths]
    # 3. Read all files
    for f in files:
        print(f.read())
