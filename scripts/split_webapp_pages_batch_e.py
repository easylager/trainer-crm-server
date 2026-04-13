#!/usr/bin/env python3
"""One-off batch: extract CSS/JS from large trainer/client Mini App HTML (Epic E)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "static" / "webapp"
V = "20260422"


def slice_lines(lines: list[str], start_1: int, end_1: int) -> str:
    """1-based inclusive start/end line numbers."""
    return "\n".join(lines[start_1 - 1 : end_1]) + "\n"


def write_stats() -> None:
    p = ROOT / "trainer-stats.html"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
    css = slice_lines(lines, 16, 1181)
    (ROOT / "mini-app-trainer-stats.css").write_text(css, encoding="utf-8")
    body = slice_lines(lines, 1185, 1208)
    js = slice_lines(lines, 1212, 1999)
    (ROOT / "trainer-stats-main.js").write_text(js, encoding="utf-8")

    head = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>Аналитика и бухгалтерия</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="mini-app-telegram-chrome.js"></script>
  <script src="client-mini-app-theme.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" media="print" onload="this.media='all'" />
  <noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" /></noscript>
  <link rel="stylesheet" href="theme.css?v={V}" />
  <link rel="stylesheet" href="mini-app-components.css?v={V}" />
  <link rel="stylesheet" href="mini-app-trainer-nav.css?v={V}" />
  <link rel="preload" href="trainer-stats-main.js?v={V}" as="script" />
  <link rel="stylesheet" href="mini-app-trainer-stats.css?v={V}" />
</head>
"""
    tail = f"""  <script src="mini-app-trainer-gate.js"></script>
  <script defer src="trainer-stats-main.js?v={V}"></script>
  <script defer src="mini-app-trainer-home.js"></script>
</body>
</html>
"""
    (ROOT / "trainer-stats.html").write_text(head + body + tail, encoding="utf-8")


def write_clients() -> None:
    p = ROOT / "trainer-clients.html"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
    theme = slice_lines(lines, 14, 38)
    css = slice_lines(lines, 41, 926)
    (ROOT / "mini-app-trainer-clients.css").write_text(css, encoding="utf-8")
    body = slice_lines(lines, 931, 964)
    js = slice_lines(lines, 967, 1937)
    (ROOT / "trainer-clients-main.js").write_text(js, encoding="utf-8")

    head = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>Мои клиенты</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="mini-app-telegram-chrome.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" media="print" onload="this.media='all'" />
  <noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" /></noscript>
  <link rel="stylesheet" href="theme.css?v={V}" />
  <link rel="stylesheet" href="mini-app-components.css?v={V}" />
{theme}  <link rel="preload" href="trainer-clients-main.js?v={V}" as="script" />
  <link rel="stylesheet" href="mini-app-trainer-clients.css?v={V}" />
  <link rel="stylesheet" href="mini-app-trainer-nav.css?v={V}" />
</head>
"""
    tail = f"""  <script src="mini-app-trainer-gate.js"></script>
  <script defer src="trainer-clients-main.js?v={V}"></script>
  <script defer src="mini-app-trainer-home.js"></script>
</body>
</html>
"""
    (ROOT / "trainer-clients.html").write_text(head + body + tail, encoding="utf-8")


def write_pass_products() -> None:
    p = ROOT / "trainer-pass-products.html"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
    theme = slice_lines(lines, 15, 40)
    css = slice_lines(lines, 42, 662)
    (ROOT / "mini-app-trainer-pass-products.css").write_text(css, encoding="utf-8")
    body = slice_lines(lines, 667, 887)
    js = slice_lines(lines, 891, 1700)
    (ROOT / "trainer-pass-products-main.js").write_text(js, encoding="utf-8")

    head = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>Абонементы и сертификаты</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="mini-app-telegram-chrome.js"></script>
  <script src="mini-app-confirm.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" media="print" onload="this.media='all'" />
  <noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" /></noscript>
  <link rel="stylesheet" href="theme.css?v={V}" />
  <link rel="stylesheet" href="mini-app-components.css?v={V}" />
{theme}  <link rel="preload" href="trainer-pass-products-main.js?v={V}" as="script" />
  <link rel="stylesheet" href="mini-app-trainer-pass-products.css?v={V}" />
  <link rel="stylesheet" href="mini-app-trainer-nav.css?v={V}" />
</head>
"""
    tail = f"""  <script src="mini-app-trainer-gate.js"></script>
  <script defer src="trainer-pass-products-main.js?v={V}"></script>
  <script defer src="mini-app-trainer-home.js"></script>
</body>
</html>
"""
    (ROOT / "trainer-pass-products.html").write_text(head + body + tail, encoding="utf-8")


def write_client_requests() -> None:
    p = ROOT / "client-requests.html"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
    css = slice_lines(lines, 17, 1010)
    (ROOT / "mini-app-client-requests.css").write_text(css, encoding="utf-8")
    body_main = slice_lines(lines, 1014, 1083)
    js = slice_lines(lines, 1085, 1901)
    (ROOT / "client-requests-main.js").write_text(js, encoding="utf-8")
    modal = slice_lines(lines, 1904, 1915)

    head = f"""<!DOCTYPE html>
<html lang="ru" data-client-requests>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>Мои заявки</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="mini-app-telegram-chrome.js"></script>
  <link rel="stylesheet" href="theme.css?v={V}" />
  <link rel="stylesheet" href="mini-app-components.css?v={V}" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" media="print" onload="this.media='all'" />
  <noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" /></noscript>
  <script src="client-mini-app-theme.js"></script>
  <script src="mini-app-confirm.js"></script>
  <link rel="preload" href="client-requests-main.js?v={V}" as="script" />
  <link rel="stylesheet" href="mini-app-client-requests.css?v={V}" />
  <link rel="stylesheet" href="mini-app-client-nav.css?v={V}" />
</head>
"""
    tail = f"""  <script defer src="client-requests-main.js?v={V}"></script>
  <script defer src="mini-app-client-home.js"></script>
</body>
</html>
"""
    (ROOT / "client-requests.html").write_text(head + body_main + modal + tail, encoding="utf-8")


def write_client_home() -> None:
    p = ROOT / "client-home.html"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
    theme = slice_lines(lines, 15, 30)
    css = slice_lines(lines, 32, 484)
    (ROOT / "mini-app-client-home.css").write_text(css, encoding="utf-8")
    body = slice_lines(lines, 487, 536)
    js = slice_lines(lines, 539, 935)
    (ROOT / "client-home-main.js").write_text(js, encoding="utf-8")

    head = f"""<!DOCTYPE html>
<html lang="ru" data-client-hub>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>Главная</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="mini-app-telegram-chrome.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" media="print" onload="this.media='all'" />
  <noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=optional" /></noscript>
  <link rel="stylesheet" href="theme.css?v={V}" />
  <link rel="stylesheet" href="mini-app-components.css?v={V}" />
  <script src="client-mini-app-theme.js"></script>
{theme}  <link rel="preload" href="client-home-main.js?v={V}" as="script" />
  <link rel="stylesheet" href="mini-app-client-home.css?v={V}" />
</head>
"""
    tail = f"""  <script defer src="client-home-main.js?v={V}"></script>
</body>
</html>
"""
    (ROOT / "client-home.html").write_text(head + body + tail, encoding="utf-8")


if __name__ == "__main__":
    write_stats()
    write_clients()
    write_pass_products()
    write_client_requests()
    write_client_home()
    print("Done. Version", V)
