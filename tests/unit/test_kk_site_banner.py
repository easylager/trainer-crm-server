"""Баннер «КТО КОГО» на главной и в городах: ведёт на лендинг с меткой места, не в бота."""

from __future__ import annotations

import re

from src.application.kk_site_banner import kk_banner_html, kk_banner_section


def test_banner_links_to_landing_with_place_label_and_loops_the_club_rail(monkeypatch) -> None:
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "1")
    html = kk_banner_html("sitehome")
    assert 'href="/kk?from=sitehome"' in html and "t.me/" not in html and "startapp=" not in html
    track = re.search(r'<div class="kkb__track">(.*?)</div>', html).group(1)
    logos = re.findall(r'<img src="([^"]+)"', track)
    half = len(logos) // 2
    assert half >= 10 and logos[:half] == logos[half:]  # дважды — петля без шва
    assert "Хоккейная игра для своей компании" in html
    assert 'id="kk"' in kk_banner_section("sitehub") and "from=sitehub" in kk_banner_section("sitehub")


def test_no_banner_while_the_game_is_off(monkeypatch) -> None:
    monkeypatch.setenv("HOCKEY_MATCHES_ENABLED", "0")
    assert kk_banner_html("sitehome") == "" and kk_banner_section("sitehub") == ""
