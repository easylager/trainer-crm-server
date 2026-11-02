"""Каждый /static/share(d)/… файл, на который ссылаются публичные страницы, отдаётся сервером.

Регрессия батча winter-26: страницы матчей и «Зимой» ссылались на CSS/JS без маршрута → 404.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import app

ROOT = Path(__file__).resolve().parents[2]
REF = re.compile(r"/static/share[d]?/[A-Za-z0-9_.-]+\.(?:css|js)")


def _referenced() -> list[str]:
    refs: set[str] = set()
    for base in (ROOT / "src" / "application", ROOT / "src" / "api", ROOT / "static" / "share"):
        for f in base.rglob("*"):
            if f.suffix in {".py", ".html"} and f.is_file():
                refs.update(REF.findall(f.read_text(encoding="utf-8", errors="ignore")))
    return sorted(refs)


@pytest.mark.parametrize("url", _referenced())
def test_referenced_public_asset_is_served(url):
    if not (ROOT / "static" / url.removeprefix("/static/")).is_file():
        pytest.skip("файла нет в репозитории — ссылка собирается динамически")
    r = TestClient(app).get(url)
    assert r.status_code == 200, url
    ctype = r.headers["content-type"]
    assert ("css" in ctype) if url.endswith(".css") else ("javascript" in ctype), (url, ctype)
