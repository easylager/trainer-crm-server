"""Read-only CrewAI tools bounded by repo allowlist (no .env / secrets paths)."""

from __future__ import annotations

import subprocess

from crewai.tools import tool

from .config import (
    LIST_DIR_MAX_DEPTH,
    MAX_READ_BYTES,
    READ_ALLOWLIST_PREFIXES,
    REPO_ROOT,
    RG_TIMEOUT_SEC,
    is_blocked_path,
    is_under_allowlisted_root,
)


def _repo_relative(path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return ""


def _validate_relative_path(user_path: str):
    """Resolve user_path under REPO_ROOT; reject escapes and blocked segments."""
    from pathlib import Path

    raw = (user_path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("..") or "/../" in raw:
        raise ValueError("Invalid path")
    candidate = (REPO_ROOT / raw).resolve()
    rel = _repo_relative(candidate)
    if not rel:
        raise ValueError("Path outside repository")
    if is_blocked_path(rel):
        raise ValueError("Path is blocked (.env / secrets)")
    if not is_under_allowlisted_root(rel):
        raise ValueError(
            f"Path not under allowed roots: {', '.join(READ_ALLOWLIST_PREFIXES)}"
        )
    return candidate


@tool("Read a text file from the repository (repo-relative path, e.g. src/api/routes.py).")
def read_project_file(relative_path: str) -> str:
    """Read a UTF-8 text file under allowlisted paths; returns error message on failure."""
    try:
        path = _validate_relative_path(relative_path)
    except ValueError as e:
        return f"ERROR: {e}"
    if not path.is_file():
        return "ERROR: not a file"
    try:
        data = path.read_bytes()[:MAX_READ_BYTES]
        return data.decode("utf-8", errors="replace")
    except OSError as e:
        return f"ERROR: {e}"


def _list_dir_recursive(base, prefix: str, depth: int, max_depth: int) -> list[str]:
    if depth > max_depth:
        return []
    out: list[str] = []
    try:
        for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            rel = f"{prefix}/{child.name}" if prefix else child.name
            out.append(rel)
            if child.is_dir():
                out.extend(_list_dir_recursive(child, rel, depth + 1, max_depth))
    except OSError:
        return out
    return out


@tool("List files under a repo-relative directory (non-hidden), limited depth.")
def list_project_dir(relative_dir: str) -> str:
    """List directory tree under allowlisted roots (max depth configured in config)."""
    try:
        path = _validate_relative_path(relative_dir.rstrip("/") or "src")
    except ValueError as e:
        return f"ERROR: {e}"
    if not path.is_dir():
        return "ERROR: not a directory"
    rel_root = _repo_relative(path)
    lines = _list_dir_recursive(path, rel_root, 0, LIST_DIR_MAX_DEPTH)
    if not lines:
        return "(empty or unreadable)"
    return "\n".join(lines[:2000]) + ("\n… (truncated)" if len(lines) > 2000 else "")


@tool("Search the repo with ripgrep (fixed flags); scope is repo-relative (default src/).")
def rg_search(pattern: str, relative_path: str = "src") -> str:
    """Run ripgrep with bounded output; requires `rg` installed."""
    if not pattern or len(pattern) > 200:
        return "ERROR: pattern empty or too long"
    try:
        scope = _validate_relative_path(relative_path.rstrip("/") or "src")
    except ValueError as e:
        return f"ERROR: {e}"
    cmd = [
        "rg",
        "--line-number",
        "--max-count",
        "50",
        "--max-columns",
        "200",
        pattern,
        str(scope),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=RG_TIMEOUT_SEC,
            check=False,
        )
    except FileNotFoundError:
        return "ERROR: ripgrep (rg) not installed; install ripgrep or search manually."
    except subprocess.TimeoutExpired:
        return "ERROR: rg timeout"
    out = (proc.stdout or "") + (proc.stderr or "")
    if len(out) > 80_000:
        return out[:80_000] + "\n… (truncated)"
    if proc.returncode not in (0, 1):
        return f"ERROR: rg exit {proc.returncode}\n{out}"
    return out or "(no matches)"


def default_repo_tools():
    """Tools shared by architect, implementer, and reviewer."""
    return [read_project_file, list_project_dir, rg_search]
