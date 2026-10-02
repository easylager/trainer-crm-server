#!/usr/bin/env python3
"""
Сборка demo.html — единый файл для выступления.

Источник (prototype.html) остаётся редактируемым: шрифты с Google Fonts,
картинки в pics/. Сборка вшивает и то и другое в base64, чтобы на выставке
демо открывалось с флешки без сети и без папок рядом.

Запуск: python3 build-demo.py
"""
import base64
import mimetypes
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "hero-proto.html"
OUT = HERE / "demo.html"
FONT_CSS = HERE / "fonts" / "embedded.css"


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> int:
    if not SRC.is_file():
        print(f"нет исходника: {SRC}")
        return 1
    if not FONT_CSS.is_file():
        print(f"нет вшитых шрифтов: {FONT_CSS}")
        return 1

    html = SRC.read_text(encoding="utf-8")

    # 1. Шрифты: убрать внешние <link> и вставить локальный @font-face.
    html = re.sub(
        r'\s*<link rel="preconnect"[^>]*>|\s*<link href="https://fonts\.googleapis[^>]*>',
        "",
        html,
    )
    html = html.replace(
        "<style>",
        "<style>\n/* Шрифты вшиты: демо не зависит от сети. */\n"
        + FONT_CSS.read_text(encoding="utf-8")
        + "\n",
        1,
    )

    # 2. Картинки: pics/... → data:. Ссылки живут и в разметке, и в JS-массиве.
    missing: list[str] = []
    for ref in sorted(set(re.findall(r"pics/[A-Za-z0-9._-]+", html))):
        f = HERE / ref
        if not f.is_file():
            missing.append(ref)
            continue
        html = html.replace(ref, data_uri(f))

    if missing:
        print("не найдены картинки: " + ", ".join(missing))
        return 1

    OUT.write_text(html, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    left = len(re.findall(r"https?://(?!fonts\.)", html))
    print(f"собрано: {OUT.name}, {kb:.0f} КБ")
    print(f"внешних ссылок осталось: {left} (0 = работает офлайн)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
