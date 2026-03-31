"""Fixed-arg pytest subprocess for optional crew iterations."""

from __future__ import annotations

import subprocess

from .config import PYTEST_ARGV, PYTEST_TIMEOUT_SEC, REPO_ROOT


def run_pytest_capture() -> tuple[int, str]:
    """Run configured pytest; return (exit_code, combined log)."""
    try:
        proc = subprocess.run(
            PYTEST_ARGV,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"pytest timed out after {PYTEST_TIMEOUT_SEC}s"
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if len(out) > 200_000:
        out = out[:200_000] + "\n… (truncated)"
    return proc.returncode, out
