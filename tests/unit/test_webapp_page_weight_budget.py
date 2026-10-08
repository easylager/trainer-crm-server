"""TASK-197: gzip weight of /webapp/ice and /webapp/catalog must not grow quietly.

The HTML names the assets. External fonts and the Telegram SDK are not ours.
Baselines are the gzip size (mtime=0, level 9) of the HTML plus each local css/js
it references, counted once. A page may shrink; growth past 5% fails CI.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_WEBAPP = _REPO / "static" / "webapp"
_ATTR = re.compile(r"""(?:src|href)=["']([^"']+)["']""", re.I)

# Gzip level 9, mtime 0. Re-measure after intentional UI growth (TASK-197 → TASK-222:
# share in list head + share-sheet). A page may shrink; growth past +5% fails CI.
_BASELINE_GZIP = {
    "ice.html": 199_458,
    "catalog.html": 200_158,
}


def _local_assets(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _ATTR.finditer(html):
        url = match.group(1).split("#", 1)[0]
        if url.startswith(("http://", "https://", "data:", "mailto:", "tel:", "viber:", "#")):
            continue
        path = url.split("?", 1)[0].lstrip("/")
        if path.startswith("webapp/"):
            path = path[len("webapp/") :]
        if not path.endswith((".js", ".css")):
            continue
        if path in seen:
            continue
        seen.add(path)
        found.append(path)
    return found


def _gzip_len(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def page_gzip_bytes(html_name: str) -> int:
    html_path = _WEBAPP / html_name
    html = html_path.read_bytes()
    total = _gzip_len(html)
    for rel in _local_assets(html.decode()):
        # /static/shared/* отдаётся от корня репозитория, остальные css/js — из static/webapp.
        asset = (_REPO / rel) if rel.startswith("static/") else (_WEBAPP / rel)
        assert asset.is_file(), f"{html_name} references missing {rel}"
        total += _gzip_len(asset.read_bytes())
    return total


def test_ice_and_catalog_page_weight_stay_within_five_percent() -> None:
    for name, baseline in _BASELINE_GZIP.items():
        size = page_gzip_bytes(name)
        assert size * 20 <= baseline * 21, f"{name} gzip {size} bytes is more than 5% over the budget {baseline}"
