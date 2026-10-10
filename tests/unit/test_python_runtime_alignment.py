"""TASK-200: prod (runtime.txt), CI workflows, and linters must agree on Python version."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def production_python_version() -> str:
    raw = (ROOT / "runtime.txt").read_text(encoding="utf-8").strip().removeprefix("python-")
    parts = raw.split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]):
        raise AssertionError(f"invalid runtime.txt: {raw!r}")
    return f"{parts[0]}.{parts[1]}"


def _py_tag(version: str) -> str:
    major, minor = version.split(".", 1)
    return f"py{major}{minor}"


def test_github_workflows_match_runtime_txt() -> None:
    runtime = production_python_version()
    workflows = ROOT / ".github" / "workflows"
    bad: list[str] = []
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"python-version:\s*['\"]?([\d.]+)", text):
            if match.group(1) != runtime:
                bad.append(f"{path.name}: python-version {match.group(1)!r}")
    assert not bad, f"runtime.txt is {runtime}; mismatches: {bad}"


def test_pyproject_toolchain_matches_runtime_txt() -> None:
    runtime = production_python_version()
    tag = _py_tag(runtime)
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff = data["tool"]["ruff"]["target-version"]
    assert ruff == tag, f"ruff target-version {ruff!r} != {tag!r} (runtime.txt {runtime})"
    black_targets = data["tool"]["black"]["target-version"]
    assert tag in black_targets, f"black target-version {black_targets!r} missing {tag!r}"
    mypy = data["tool"]["mypy"]["python_version"]
    assert mypy == runtime, f"mypy python_version {mypy!r} != runtime {runtime!r}"
