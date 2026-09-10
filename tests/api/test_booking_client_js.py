"""TASK-109: hub nearest-slot back stack + BYN letters (no NBRB tofu)."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_booking_client_node_unit() -> None:
    proc = subprocess.run(
        ["node", "--test", "tests/js/booking-client.test.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
