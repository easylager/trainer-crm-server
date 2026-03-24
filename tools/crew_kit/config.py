"""Paths, allowlists, and fixed subprocess commands for crew_kit."""

from __future__ import annotations

import os
from pathlib import Path

# Repo root: tools/crew_kit/config.py -> parents[2]
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# Read-only roots relative to REPO_ROOT (prefix match after resolve).
READ_ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "src/",
    "specs/",
    "static/webapp/",
    "migrations/",
    "tests/",
    "docs/",
)

# Basenames and path fragments that must never be read via tools.
BLOCKED_PATH_PARTS: tuple[str, ...] = (
    ".env",
    ".pem",
    "id_rsa",
    "credentials",
)

# Artifacts live under the feature spec directory.
CREW_ARTIFACTS_DIRNAME = "crew_artifacts"

# Pytest: fixed argv only (no LLM-controlled shell).
PYTEST_ARGV: list[str] = ["pytest", "-q", "tests/"]
PYTEST_TIMEOUT_SEC: int = int(os.environ.get("CREW_PYTEST_TIMEOUT", "300"))

# Optional model override (OpenRouter: e.g. openai/gpt-4o-mini)
DEFAULT_CREW_MODEL = os.environ.get("CREW_MODEL", "gpt-4o-mini")

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

# rg timeout
RG_TIMEOUT_SEC: int = int(os.environ.get("CREW_RG_TIMEOUT", "45"))

# Max bytes read per file
MAX_READ_BYTES: int = 512_000

# list_dir max depth from the requested directory
LIST_DIR_MAX_DEPTH: int = 4


def is_under_allowlisted_root(rel: str) -> bool:
    """Return True if normalized repo-relative path starts with an allowed prefix."""
    p = rel.replace("\\", "/").lstrip("/")
    for prefix in READ_ALLOWLIST_PREFIXES:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            return True
    return False


def is_blocked_path(rel: str) -> bool:
    lower = rel.lower()
    return any(part in lower for part in BLOCKED_PATH_PARTS)
