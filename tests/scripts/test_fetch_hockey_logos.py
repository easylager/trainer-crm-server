"""TASK-299: логотипы клубов берём оригиналом 200×200, а не уменьшенной копией Битрикса."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fetch_hockey_logos.py"
_spec = importlib.util.spec_from_file_location("fetch_hockey_logos", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_original_url_strips_resize_cache() -> None:
    assert (
        _mod.original_url("https://hcdinamo.by/upload/resize_cache/iblock/cdb/59_59_1/dinamo_mn_2019.png")
        == "https://hcdinamo.by/upload/iblock/cdb/dinamo_mn_2019.png"
    )
    assert (
        _mod.original_url(
            "https://hcdinamo.by/upload/resize_cache/iblock/76a/g6oq0235yay3awlt9n4fkwjqi4sktote/59_59_1/ak_bars_2022-200x200.png"
        )
        == "https://hcdinamo.by/upload/iblock/76a/g6oq0235yay3awlt9n4fkwjqi4sktote/ak_bars_2022-200x200.png"
    )
    plain = "https://hcdinamo.by/upload/iblock/7f6/x/Sochi_logo_2024_40.png"
    assert _mod.original_url(plain) == plain
