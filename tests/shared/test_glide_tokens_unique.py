"""Токен в одном блоке glide-tokens.css объявлен один раз: второе объявление молча перебивает первое.

TASK-278: --g-tg (синий кнопки) затёр --g-tg иконки «Поделиться» ниже в том же :root —
кнопка вышла светлее и с белым текстом ~3:1 вместо ~5:1.
"""

from __future__ import annotations

import re
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[2] / "static" / "shared" / "glide-tokens.css"


def test_no_token_is_declared_twice_in_one_block() -> None:
    css = re.sub(r"/\*.*?\*/", "", TOKENS.read_text(encoding="utf-8"), flags=re.S)
    duplicates = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        names = re.findall(r"(--[\w-]+)\s*:", body)
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            duplicates.append((selector.strip(), repeated))
    assert duplicates == []


def test_telegram_button_blue_stays_dark_enough_for_white_text() -> None:
    css = TOKENS.read_text(encoding="utf-8")
    assert "--g-tg-btn: #1873b8;" in css
    assert "--g-tg: #229ed9;" in css
