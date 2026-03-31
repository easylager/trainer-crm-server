"""Allow `python -m tools.crew_kit` from repository root (PYTHONPATH includes repo root)."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
