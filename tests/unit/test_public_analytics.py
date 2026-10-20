"""Публичные счётчики Метрики / GA4."""

from src.application.public_analytics import public_analytics_head_html


def test_public_analytics_empty_when_unconfigured() -> None:
    assert public_analytics_head_html() == ""


def test_public_analytics_metrika_snippet() -> None:
    html = public_analytics_head_html(yandex_metrika_counter_id=46475025)
    assert "ym(46475025" in html
    assert "ssr:true" in html
    assert "webvisor:false" in html
    assert "metrika/tag.js?id=46475025" in html
    assert "mc.yandex.ru/watch/46475025" in html


def test_public_analytics_ga4_snippet() -> None:
    html = public_analytics_head_html(google_analytics_measurement_id="G-ABC123XYZ")
    assert "googletagmanager.com/gtag/js?id=G-ABC123XYZ" in html
    assert "gtag('config', 'G-ABC123XYZ')" in html


def test_public_analytics_rejects_invalid_ga4_id() -> None:
    assert public_analytics_head_html(google_analytics_measurement_id="not-valid") == ""
