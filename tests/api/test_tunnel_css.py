"""Туннель: стили мини-приложения вшиваются в HTML, внешние ссылки остаются."""

from src.api.tunnel_css import inline_tunnel_styles, tunnel_host


def test_tunnel_host_is_ngrok_or_cloudflare() -> None:
    assert tunnel_host("spoon.ngrok-free.dev")
    assert tunnel_host("name.trycloudflare.com")
    assert not tunnel_host("glideclub.by")
    assert not tunnel_host("127.0.0.1:8000")


def test_shared_and_local_stylesheets_are_inlined() -> None:
    html = (
        '<link rel="stylesheet" href="/static/shared/glide-tokens.css?v=1" />'
        '<link rel="stylesheet" href="theme.css?v=1" />'
        '<link rel="stylesheet" href="https://fonts.example/x.css" />'
    )
    out = inline_tunnel_styles(html)
    assert "--g-bg:" in out
    assert "https://fonts.example/x.css" in out
    assert out.count("<style>") == 2
    assert out.count('<link rel="stylesheet" href="https://fonts.example/x.css"') == 1


def test_local_scripts_are_inlined_external_stay() -> None:
    html = (
        '<script defer src="mini-app-telegram-chrome.js?v=1"></script>'
        '<script src="/static/webapp/client-match.js?v=1"></script>'
        '<script src="https://telegram.org/js/telegram-web-app.js"></script>'
    )
    out = inline_tunnel_styles(html)
    assert "function paintHero" in out
    assert "DOMContentLoaded" in out
    assert 'src="https://telegram.org/js/telegram-web-app.js"' in out
    assert 'src="/static/webapp/client-match.js' not in out
    assert 'src="mini-app-telegram-chrome.js' not in out
