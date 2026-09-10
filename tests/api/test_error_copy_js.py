"""TASK-111 Task 5 wrapper for the focused frontend error contract."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_error_copy_node_contract() -> None:
    proc = subprocess.run(
        ["node", "--test", "tests/js/error-copy.test.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
