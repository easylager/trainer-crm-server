"""Outer loop: architect once, then implement/review iterations with optional pytest."""

from __future__ import annotations

from pathlib import Path

from .config import CREW_ARTIFACTS_DIRNAME, REPO_ROOT
from .crew_runner import (
    build_agents,
    make_llm,
    run_architect_crew,
    run_implement_review_crew,
)
from .loaders import build_system_context
from .pytest_runner import run_pytest_capture
from .verdict import parse_verdict


def _ensure_artifacts_dir(feature_dir: Path) -> Path:
    out = feature_dir / CREW_ARTIFACTS_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def run_crew_loop(
    *,
    feature_dir: Path,
    max_iters: int,
    verbose: bool,
    run_pytest: bool,
) -> int:
    """
    Execute architect + implement/review loop. Returns process exit code (0 if PASS, 1 otherwise).
    """
    feature_dir = feature_dir.resolve()
    if not feature_dir.is_dir():
        raise FileNotFoundError(f"Feature dir not found: {feature_dir}")

    artifacts = _ensure_artifacts_dir(feature_dir)
    system_context = build_system_context(feature_dir)
    _write(artifacts / "00_system_context.md", system_context)

    llm = make_llm(verbose=verbose)
    architect, implementer, reviewer = build_agents(llm, verbose=verbose)

    design_note = run_architect_crew(
        architect=architect,
        system_context=system_context,
        verbose=verbose,
    )
    _write(artifacts / "01_architect.md", design_note)

    previous_review = ""
    pytest_log = ""
    last_verdict: str | None = None

    for i in range(1, max_iters + 1):
        impl_text, review_text = run_implement_review_crew(
            implementer=implementer,
            reviewer=reviewer,
            system_context=system_context,
            design_note=design_note,
            iteration=i,
            previous_review=previous_review,
            pytest_log=pytest_log,
            verbose=verbose,
        )
        combined = (
            f"# Iteration {i} — Implementer\n\n{impl_text}\n\n"
            f"# Iteration {i} — Reviewer\n\n{review_text}\n"
        )
        _write(artifacts / f"iteration_{i:02d}.md", combined)

        proposed = artifacts / f"iteration_{i:02d}_proposed.diff"
        proposed.write_text(impl_text, encoding="utf-8")

        last_verdict = parse_verdict(review_text)
        previous_review = review_text

        if run_pytest:
            code, log = run_pytest_capture()
            pytest_path = artifacts / f"iteration_{i:02d}_pytest.log"
            pytest_header = f"exit_code={code}\n\n"
            _write(pytest_path, pytest_header + log)
            pytest_log = pytest_header + log

        if last_verdict == "PASS":
            _write(
                artifacts / "final_summary.md",
                f"Result: PASS after iteration {i}.\n\n"
                f"Artifacts under `{artifacts.relative_to(REPO_ROOT)}`.\n",
            )
            return 0

    _write(
        artifacts / "final_summary.md",
        f"Result: no PASS within {max_iters} iteration(s). "
        f"Last parsed verdict: {last_verdict!r}.\n",
    )
    return 1
