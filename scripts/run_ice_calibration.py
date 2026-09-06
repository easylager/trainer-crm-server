"""Print Minsk MK extract calibration metrics (TASK-066 / TASK-062 hook).

Usage:
  PYTHONPATH=. python scripts/run_ice_calibration.py
  PYTHONPATH=. python scripts/run_ice_calibration.py --check
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ingestion.calibration import main

if __name__ == "__main__":
    raise SystemExit(main())
