"""TASK-340: игра «Кто кого» видит только матчи Динамо — Экстралига лежит в той же таблице."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src/application"

# Модули игры: ходы, лиги, гонки, напоминания, карточки и слот игры на главной.
GAME_MODULES = ("hockey_game", "hockey_leagues", "hockey_races", "hockey_notices", "hockey_share", "hockey_hub")
_DIRECT = re.compile(r"\b(?:FROM|JOIN)\s+hockey_matches\b", re.I)


@pytest.mark.parametrize("module", GAME_MODULES)
def test_game_module_reads_only_kk_matches(module: str) -> None:
    source = (SRC / f"{module}.py").read_text(encoding="utf-8")
    hits = [line.strip() for line in source.splitlines() if _DIRECT.search(line)]
    assert not hits, f"{module} читает hockey_matches напрямую — нужна kk_matches: {hits}"


def test_dinamo_result_checker_ignores_other_sources() -> None:
    source = (SRC / "hockey_matches.py").read_text(encoding="utf-8")
    for name in ("_DUE", "_STALE", "_HOT"):
        block = re.search(rf"{name} = text\(f?\"\"\"(.*?)\"\"\"\)", source, re.S)
        assert block and "FROM kk_matches" in block.group(1), name
