"""Load Spec Kit files and constitution excerpts for agent context."""

from __future__ import annotations

from pathlib import Path

from .config import REPO_ROOT


def _read_if_exists(path: Path, label: str) -> str:
    if not path.is_file():
        return f"({label} missing at {path.relative_to(REPO_ROOT)})\n"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        return f"({label} read error: {e})\n"


def load_feature_docs(feature_dir: Path) -> str:
    """Concatenate spec.md, plan.md, tasks.md from a feature folder."""
    parts: list[str] = []
    for name in ("spec.md", "plan.md", "tasks.md"):
        p = feature_dir / name
        parts.append(f"## {name}\n\n")
        parts.append(_read_if_exists(p, name))
        parts.append("\n")
    return "".join(parts)


def load_constitution(max_chars: int = 24_000) -> str:
    """Load full constitution (trimmed if extremely large)."""
    path = REPO_ROOT / ".specify" / "memory" / "constitution.md"
    text = _read_if_exists(path, "constitution.md")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n… (truncated for context)\n"
    return text


def build_system_context(feature_dir: Path) -> str:
    """Single blob for task descriptions: feature docs + constitution."""
    return (
        "# Project constitution\n\n"
        + load_constitution()
        + "\n\n# Feature documents\n\n"
        + load_feature_docs(feature_dir)
    )


def dry_run_info(feature_dir: Path) -> str:
    """Human-readable summary without CrewAI (for CLI --dry-run)."""
    feature_dir = feature_dir.resolve()
    ctx = build_system_context(feature_dir)
    prompts_dir = Path(__file__).resolve().parent / "prompts" / "architect.md"
    arch_len = len(prompts_dir.read_text(encoding="utf-8")) if prompts_dir.is_file() else 0
    return (
        f"Feature dir: {feature_dir}\n"
        f"Context chars: {len(ctx)}\n"
        f"Architect prompt file chars: {arch_len}\n"
    )
