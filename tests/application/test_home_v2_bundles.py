"""TASK-448: бандлы главной v2 — порядок склейки, версия по содержимому, подмена региона."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.application import home_v2_bundles as bundles


@pytest.fixture(autouse=True)
def _clear_bundle_cache():
    bundles._cache.clear()
    yield
    bundles._cache.clear()


def test_bundle_is_ordered_concatenation() -> None:
    version, body = bundles.build_bundle("head.js")
    pos = 0
    for rel in bundles.HEAD_JS:
        src = (bundles._STATIC_DIR / rel).read_text(encoding="utf-8")
        part = f"/* file: {rel} */\n{src}"
        assert body.find(part, pos) == pos, rel
        pos += len(part) + 2  # + разделитель ";\n"
    assert body == ";\n".join(
        f"/* file: {rel} */\n{(bundles._STATIC_DIR / rel).read_text(encoding='utf-8')}"
        for rel in bundles.HEAD_JS
    )
    assert version == hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def test_css_bundle_is_ordered_concatenation() -> None:
    _v, body = bundles.build_bundle("bundle.css")
    for rel in bundles.CSS:
        assert f"/* file: {rel} */" in body
    positions = [body.index(f"/* file: {rel} */") for rel in bundles.CSS]
    assert positions == sorted(positions)


def test_version_changes_with_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "webapp").mkdir(parents=True)
    (static / "shared").mkdir(parents=True)
    for rel in bundles.HEAD_JS + bundles.APP_JS + bundles.CSS:
        (static / rel).write_text(f"/* {rel} */\n", encoding="utf-8")
    monkeypatch.setattr(bundles, "_STATIC_DIR", static)
    bundles._cache.clear()
    v1, _ = bundles.build_bundle("head.js")
    (static / bundles.HEAD_JS[0]).write_text("/* changed */\n", encoding="utf-8")
    bundles._cache.clear()
    v2, body2 = bundles.build_bundle("head.js")
    assert v1 != v2
    assert "/* changed */" in body2


def test_missing_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundles, "_STATIC_DIR", tmp_path)
    bundles._cache.clear()
    with pytest.raises(FileNotFoundError):
        bundles.build_bundle("head.js")


def test_apply_bundles_replaces_first_region_and_clears_rest() -> None:
    html = Path("static/webapp/client-home-v2.html").read_text(encoding="utf-8")
    out = bundles.apply_bundles(html)
    assert out is not None
    assert "/webapp/home-v2.bundle.css?v=" in out
    assert "/webapp/home-v2.head.js?v=" in out
    assert "/webapp/home-v2.app.js?v=" in out
    # Одиночные ассеты из региона ушли; вне региона (telegram sdk, инлайны) — на месте.
    assert 'src="glide-deeplink.js' not in out
    assert 'src="home-v2.js' not in out
    assert "telegram.org/js/telegram-web-app.js" in out
    assert "__clientEarlyBootstrap" in out


def test_apply_bundles_no_region_returns_none() -> None:
    assert bundles.apply_bundles("<html><head></head></html>") is None


def test_apply_bundles_fail_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundles, "bundle_tags", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    html = "<head><!-- s3:assets --><script src=x.js></script><!-- /s3:assets --></head>"
    assert bundles.apply_bundles(html) is None
