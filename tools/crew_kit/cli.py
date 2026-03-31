"""CLI entry for local CrewAI runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import REPO_ROOT
from .loaders import dry_run_info


def _load_dotenv() -> None:
    """Load repo-root `.env` so OPENAI_API_KEY / CREW_* work without manual export."""
    env_path = REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(
        description="Spec-driven CrewAI loop (architect → implement/review). "
        "Writes outputs under <feature-dir>/crew_artifacts/.",
    )
    parser.add_argument(
        "--feature-dir",
        type=Path,
        required=True,
        help="Path to specs/<branch>-<slug>/ containing spec.md, plan.md, tasks.md",
    )
    parser.add_argument(
        "--max-iters",
        type=int,
        default=3,
        help="Maximum implement/review iterations (default: 3)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose CrewAI / agent logging",
    )
    parser.add_argument(
        "--run-pytest",
        action="store_true",
        help="After each iteration, run fixed pytest command and feed log to the next iteration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load specs and print context stats without calling the LLM",
    )
    args = parser.parse_args(argv)

    feature_dir = args.feature_dir
    if not feature_dir.is_absolute():
        feature_dir = (REPO_ROOT / feature_dir).resolve()

    if args.dry_run:
        print(dry_run_info(feature_dir))
        return 0

    from .loop import run_crew_loop

    try:
        return run_crew_loop(
            feature_dir=feature_dir,
            max_iters=max(1, args.max_iters),
            verbose=args.verbose,
            run_pytest=args.run_pytest,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    except Exception as e:
        print(f"crew_kit error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
