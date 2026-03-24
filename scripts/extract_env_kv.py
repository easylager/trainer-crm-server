#!/usr/bin/env python3
"""Read a single KEY from repo-root .env without shell-sourcing (avoids invalid lines breaking MCP)."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: extract_env_kv.py KEY", file=sys.stderr)
        sys.exit(2)
    key = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    path = root / ".env"
    if not path.is_file():
        sys.exit(1)
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m or m.group(1) != key:
            continue
        v = m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        sys.stdout.write(v)
        return
    sys.exit(1)


if __name__ == "__main__":
    main()
