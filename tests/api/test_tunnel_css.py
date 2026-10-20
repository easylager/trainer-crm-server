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


def test_deferred_script_own_domcontentloaded_still_runs(tmp_path) -> None:
    """Каталог тренера висел на «Загрузка»: defer-скрипт вешает загрузку на DOMContentLoaded, а
    встроенный код уже выполнялся внутри этого события. Подписки должны сработать, по порядку."""
    import re as _re
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        import pytest

        pytest.skip("node is not installed")
    out = inline_tunnel_styles(
        "<html><body>"
        '<script defer src="trainer-catalog-main.js?v=1"></script>'
        '<script defer src="mini-app-telegram-chrome.js?v=1"></script>'
        "</body></html>"
    )
    scripts = _re.findall(r"<script>(.*?)</script>", out, flags=_re.S)
    assert len(scripts) == 3, "два встроенных defer-скрипта и сбор подписок последним"
    # Тело скриптов подменяем пробой: важен порядок и то, что поздняя подписка срабатывает.
    probe = [
        s.replace(s[s.index("try{\n") + 5 : s.index("\n}finally")], body)
        for s, body in zip(
            scripts[:2],
            [
                "log.push('a-run');document.addEventListener('DOMContentLoaded',function(){log.push('a-dcl')});",
                "log.push('b-run');",
            ],
        )
    ] + [scripts[2]]
    harness = tmp_path / "h.js"
    harness.write_text(
        "var log=[];var ls=[];var window={};"
        "var document={addEventListener:function(t,f){ls.push([t,f]);}};"
        "function Event(t){this.type=t;}"
        + "\n".join(probe)
        + "\nfor(var i=0;i<ls.length;i++){if(ls[i][0]==='DOMContentLoaded')ls[i][1].call(document);}"
        "console.log(log.join(','));",
        encoding="utf-8",
    )
    res = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=20)
    assert res.stdout.strip() == "a-run,b-run,a-dcl", res.stderr
