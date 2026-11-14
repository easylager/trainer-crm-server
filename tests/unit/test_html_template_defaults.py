"""``__OG_TYPE__`` в b.html: страница, которая его не задала, получает ``website``, а не сырую метку."""

from __future__ import annotations

from pathlib import Path

from src.shared.html_template import fill_placeholders

B_HTML = (Path(__file__).resolve().parents[2] / "static" / "share" / "b.html").read_text(encoding="utf-8")


def test_og_type_defaults_to_website_and_can_be_overridden() -> None:
    assert '<meta property="og:type" content="__OG_TYPE__"' in B_HTML
    plain = fill_placeholders(B_HTML, {})
    assert '<meta property="og:type" content="website" />' in plain
    assert "__OG_TYPE__" not in plain
    assert '<meta property="og:type" content="profile" />' in fill_placeholders(B_HTML, {"__OG_TYPE__": "profile"})
    # Волна 0: без контекста плейсхолдер не утекает в HTML.
    assert "__GLIDE_TRACK__" not in fill_placeholders(B_HTML, {})
    # Незнакомые метки по-прежнему остаются как есть (контракт fill_placeholders).
    assert fill_placeholders("__NO_SUCH__", {}) == "__NO_SUCH__"
