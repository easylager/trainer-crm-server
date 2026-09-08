#!/usr/bin/env python3
"""Пересобирает .ai/tasks/INDEX.md из frontmatter файлов задач.

INDEX.md — удобство для человека, а не источник правды: правится только этим
скриптом, руками — никогда. Источник правды — сами TASK-NNN.md.
"""

from __future__ import annotations

import pathlib
import re
import sys

STATUS_ORDER = [
    "EXECUTING",
    "VERIFYING",
    "RECOVERABLE",
    "REPLAN_REQUIRED",
    "BLOCKED",
    "READY",
    "COMPLETE",
]
VALID_STATUS = set(STATUS_ORDER)
VALID_PHASE = {
    "new", "clarify", "design", "creative-explore", "plan",
    "estimate", "implement", "verify", "design-review", "review",
}


def field(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{key}:\s*(.+)$", text)
    return match.group(1).strip() if match else ""


def main() -> int:
    tasks_dir = pathlib.Path(".ai/tasks")
    if not tasks_dir.is_dir():
        print("нет .ai/tasks — нечего индексировать", file=sys.stderr)
        return 1

    rows, problems = [], []
    for path in sorted(tasks_dir.glob("TASK-*.md")):
        text = path.read_text(encoding="utf-8")
        status, phase = field(text, "status"), field(text, "phase")
        rows.append(
            {
                "id": path.stem,
                "status": status,
                "phase": phase,
                "title": field(text, "title") or "—",
                "branch": field(text, "branch"),
            }
        )
        if status not in VALID_STATUS:
            problems.append(f"{path.stem}: недопустимый status `{status or 'пусто'}`")
        if phase not in VALID_PHASE:
            problems.append(f"{path.stem}: недопустимый phase `{phase or 'пусто'}`")

    lines = ["# Задачи", "", f"Всего: {len(rows)}. Пересоберите: `python3 scripts/ai_index.py`.", ""]
    for status in STATUS_ORDER:
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        lines.append(f"## {status} ({len(group)})")
        lines.append("")
        for r in group:
            branch = f" · `{r['branch']}`" if r["branch"] else ""
            lines.append(f"- **{r['id']}** [{r['phase']}] {r['title']}{branch}")
        lines.append("")

    if problems:
        lines += ["## Требуют внимания", ""] + [f"- {p}" for p in problems] + [""]

    (tasks_dir / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"INDEX.md пересобран: {len(rows)} задач, проблем: {len(problems)}")
    for p in problems:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
