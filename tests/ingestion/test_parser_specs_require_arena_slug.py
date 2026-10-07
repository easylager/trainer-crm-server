"""Test that every parser spec with a parser_key defines arena_slug and city (TASK-196)."""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PARSERS_DIR = REPO_ROOT / "data/parsers"


def parse_spec_headers(text: str) -> dict[str, str]:
    """Parse YAML-style headers from spec markdown."""
    header_re = re.compile(
        r"^-\s*(arena_id|arena_slug|city|city_name|parser_key|cadence|requires_by_egress|slug):\s*(.+?)\s*$",
        re.M,
    )
    headers = {}
    for match in header_re.finditer(text):
        headers[match.group(1)] = match.group(2).strip()
    return headers


def test_all_specs_with_parser_key_have_arena_slug():
    """Every spec with a parser_key must define arena_slug and city/city_name (stable key for TASK-196).
    
    Exception: mozyr-global-ice uses "slug" instead of "arena_slug" (special case).
    """
    missing = []
    
    for spec_path in sorted(PARSERS_DIR.glob("*.md")):
        if spec_path.name == "README.md":
            continue
        
        text = spec_path.read_text(encoding="utf-8")
        headers = parse_spec_headers(text)
        
        parser_key = headers.get("parser_key")
        if not parser_key or parser_key.lower() in {"null", "~", "none", ""}:
            continue
        
        # Check for arena_slug or slug (mozyr-global-ice special case)
        arena_slug = headers.get("arena_slug") or headers.get("slug")
        city = headers.get("city") or headers.get("city_name")
        
        if not arena_slug:
            missing.append(f"{spec_path.name}: missing arena_slug (parser_key={parser_key})")
        if not city:
            missing.append(f"{spec_path.name}: missing city/city_name (parser_key={parser_key})")
    
    if missing:
        pytest.fail(
            f"TASK-196: {len(missing)} parser spec(s) missing arena_slug or city:\n" + "\n".join(f"  - {m}" for m in missing)
        )
