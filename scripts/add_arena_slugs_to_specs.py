#!/usr/bin/env python3
"""Add arena_slug and city headers to parser specs that have parser_key but miss arena_slug."""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "data/fixtures"
PARSERS_DIR = REPO_ROOT / "data/parsers"

# Mapping from arena_slug (fixture dir name) to city_name
# For Minsk: city is always "Минск"
# For SPb: city is "Санкт-Петербург"
# For Moscow: city is "Москва"
# For regional BY: read from expected.json or scripts/seed_regional_arenas.py

REGIONAL_CITIES = {
    "brest-lds": "Брест",
    "baranovichi-lds": "Барановичи",
    "kobrin-lds": "Кобрин",
    "pinsk-volna": "Пинск",
    "grodno-triniti": "Гродно",
    "grodno-neman": "Гродно",
    "lida-lds": "Лида",
    "novopolotsk-lds": "Новополоцк",
    "vitebsk-ds": "Витебск",
    "mogilev-ds": "Могилёв",
    "orsha-arena": "Орша",
    "gorki-lds": "Горки",
    "ostrovets-lds": "Островец",
    "bobruisk-arena": "Бобруйск",
    "molodechno-src": "Молодечно",
    "soligorsk-szk": "Солигорск",
    "shklov-arena": "Шклов",
    "gomel-lds": "Гомель",
    "raubichi-rcop": "Раубичи",
    "zhodino-sdyushor": "Жодино",
    "silichi-rgc": "Силичи",
    "bereza-lds": "Береза",
    "ivatsevichi-lds": "Ивацевичи",
    "luninets-olimp": "Лунинец",
    "pruzhany-sdyushor": "Пружаны",
}


def infer_city_from_slug(arena_slug: str, expected_json: dict) -> str:
    """Infer city name from arena_slug and expected.json."""
    # Check if city is in expected.json
    if "city" in expected_json:
        return expected_json["city"]
    
    # Check prefixes
    if arena_slug.startswith("minsk-"):
        return "Минск"
    if arena_slug.startswith("spb-"):
        return "Санкт-Петербург"
    if arena_slug.startswith("msk-"):
        return "Москва"
    
    # Regional BY arenas
    if arena_slug in REGIONAL_CITIES:
        return REGIONAL_CITIES[arena_slug]
    
    # Fallback: try to read from expected.json
    raise ValueError(f"Cannot infer city for arena_slug={arena_slug}")


def load_fixture_metadata() -> dict[str, tuple[str, str]]:
    """Load (arena_slug, city_name) from fixtures.
    
    Returns: {spec_stem: (arena_slug, city_name)}
    """
    metadata = {}
    for fixture_dir in FIXTURES_DIR.iterdir():
        if not fixture_dir.is_dir():
            continue
        expected_path = fixture_dir / "expected.json"
        if not expected_path.is_file():
            continue
        
        arena_slug = fixture_dir.name
        try:
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"WARNING: Failed to parse {expected_path}: {e}")
            continue
        
        city_name = infer_city_from_slug(arena_slug, expected)
        
        # Map spec stem (fixture dir name) to (arena_slug, city_name)
        # Spec stem usually matches fixture dir name
        metadata[arena_slug] = (arena_slug, city_name)
    
    return metadata


def parse_spec_headers(text: str) -> dict[str, str]:
    """Parse YAML-style headers from spec markdown."""
    header_re = re.compile(r"^-\s*(arena_id|arena_slug|city|city_name|parser_key|cadence|requires_by_egress):\s*(.+?)\s*$", re.M)
    headers = {}
    for match in header_re.finditer(text):
        headers[match.group(1)] = match.group(2).strip()
    return headers


def add_arena_slug_to_spec(spec_path: Path, arena_slug: str, city_name: str) -> bool:
    """Add arena_slug and city headers to spec if missing. Returns True if modified."""
    text = spec_path.read_text(encoding="utf-8")
    headers = parse_spec_headers(text)
    
    # Check if arena_slug already exists
    if "arena_slug" in headers:
        return False
    
    # Check if parser_key exists
    parser_key = headers.get("parser_key")
    if not parser_key or parser_key.lower() in {"null", "~", "none"}:
        return False
    
    # Find insertion point: after arena_id or at the beginning of headers
    lines = text.splitlines(keepends=True)
    insert_idx = None
    
    for i, line in enumerate(lines):
        if re.match(r"^-\s*arena_id:", line):
            insert_idx = i + 1
            break
    
    if insert_idx is None:
        # Find first header line
        for i, line in enumerate(lines):
            if re.match(r"^-\s*\w+:", line):
                insert_idx = i
                break
    
    if insert_idx is None:
        print(f"WARNING: Cannot find header insertion point in {spec_path}")
        return False
    
    # Insert arena_slug and city
    new_lines = lines[:insert_idx]
    new_lines.append(f"- arena_slug: {arena_slug}\n")
    if "city" not in headers and "city_name" not in headers:
        new_lines.append(f"- city: {city_name}\n")
    new_lines.extend(lines[insert_idx:])
    
    spec_path.write_text("".join(new_lines), encoding="utf-8")
    return True


def main():
    metadata = load_fixture_metadata()
    print(f"Loaded {len(metadata)} fixture metadata entries")
    
    # Find all specs with parser_key but without arena_slug
    specs_updated = 0
    specs_without_fixture = []
    
    for spec_path in sorted(PARSERS_DIR.glob("*.md")):
        if spec_path.name == "README.md":
            continue
        
        text = spec_path.read_text(encoding="utf-8")
        headers = parse_spec_headers(text)
        
        parser_key = headers.get("parser_key")
        if not parser_key or parser_key.lower() in {"null", "~", "none"}:
            continue
        
        if "arena_slug" in headers:
            continue
        
        # Try to find matching fixture by spec stem
        spec_stem = spec_path.stem
        if spec_stem not in metadata:
            specs_without_fixture.append(spec_stem)
            continue
        
        arena_slug, city_name = metadata[spec_stem]
        if add_arena_slug_to_spec(spec_path, arena_slug, city_name):
            print(f"Updated {spec_path.name}: arena_slug={arena_slug}, city={city_name}")
            specs_updated += 1
    
    print(f"\nUpdated {specs_updated} specs")
    if specs_without_fixture:
        print(f"WARNING: {len(specs_without_fixture)} specs without matching fixture:")
        for stem in specs_without_fixture:
            print(f"  - {stem}")


if __name__ == "__main__":
    main()
