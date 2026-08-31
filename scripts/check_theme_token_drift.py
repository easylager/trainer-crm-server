#!/usr/bin/env python3
"""
Сверка токенов темы между theme.css и двумя theme-JS (TASK-017, AC-003).

Зачем. Оба theme-JS выставляют ~10 токенов инлайном на <html> с флагом
`important`, поэтому при расхождении с theme.css выигрывает JS, а написанное
в CSS просто не применяется — молча. Так уже случалось: светлый CTA в
theme.css был янтарным, а пользователи год видели тил.

Скрипт парсит эталон из theme.css и сверяет с константами в обоих JS.
Код возврата: 0 — совпадает, 1 — расхождение, 2 — не удалось разобрать файлы.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEBAPP = REPO / "static" / "webapp"

THEME_CSS = WEBAPP / "theme.css"
THEME_JS = (
    WEBAPP / "mini-app-trainer-theme.js",
    WEBAPP / "client-mini-app-theme.js",
)

# Селектор, открывающий блок тёмной темы ARENA.
DARK_SELECTOR = "html.trainer-theme-dark"

# Константа в JS -> (тема, кастомное свойство в theme.css).
MAPPING: dict[str, tuple[str, str]] = {
    "GLIDE_CTA_FILL": ("light", "--glide-500"),
    "GLIDE_CTA_TEXT": ("light", "--glide-on-fill"),
    "ACCENT_RGB": ("light", "--accent-rgb"),
    "LIGHT_BG": ("light", "--glide-paper"),
    "LIGHT_SURFACE": ("light", "--glide-surface"),
    "LIGHT_TEXT": ("light", "--glide-text"),
    "LIGHT_HINT": ("light", "--glide-hint"),
    "DARK_BG": ("dark", "--glide-paper"),
    "DARK_SURFACE": ("dark", "--glide-surface"),
    "DARK_TEXT": ("dark", "--glide-text"),
    "DARK_HINT": ("dark", "--glide-hint"),
}


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block_after(css: str, open_brace_at: int) -> str:
    """Вернуть содержимое блока, начиная с позиции его открывающей скобки."""
    depth = 0
    for i in range(open_brace_at, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace_at + 1 : i]
    raise ValueError("не найдена закрывающая скобка блока")


def _find_block(css: str, selector: str) -> str:
    idx = css.find(selector)
    if idx == -1:
        raise ValueError(f"не найден селектор {selector!r}")
    brace = css.find("{", idx)
    if brace == -1:
        raise ValueError(f"нет открывающей скобки после {selector!r}")
    return _block_after(css, brace)


def _declarations(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block):
        out[name] = value.strip()
    return out


def normalize(value: str) -> str:
    """Привести к сравнимому виду: регистр hex и пробелы значения не несут."""
    v = " ".join(value.split()).strip().strip("'\"")
    return v.lower()


def read_css_tokens() -> dict[tuple[str, str], str]:
    css = _strip_comments(THEME_CSS.read_text(encoding="utf-8"))
    light = _declarations(_find_block(css, ":root"))
    dark = _declarations(_find_block(css, DARK_SELECTOR))
    # Тёмный блок переопределяет не всё — недостающее наследуется из :root.
    merged_dark = {**light, **dark}
    return {
        **{("light", k): v for k, v in light.items()},
        **{("dark", k): v for k, v in merged_dark.items()},
    }


def read_js_constants(path: Path) -> dict[str, str]:
    src = path.read_text(encoding="utf-8")
    return {
        name: value
        for name, value in re.findall(r"var\s+([A-Z][A-Z0-9_]*)\s*=\s*'([^']*)'", src)
    }


def main() -> int:
    try:
        css_tokens = read_css_tokens()
    except (OSError, ValueError) as exc:
        print(f"Не удалось разобрать theme.css: {exc}", file=sys.stderr)
        return 2

    problems: list[str] = []
    checked = 0

    for js_path in THEME_JS:
        try:
            consts = read_js_constants(js_path)
        except OSError as exc:
            print(f"Не удалось прочитать {js_path.name}: {exc}", file=sys.stderr)
            return 2

        for const_name, (scope, css_prop) in MAPPING.items():
            css_value = css_tokens.get((scope, css_prop))
            if css_value is None:
                problems.append(
                    f"{js_path.name}: в theme.css нет {css_prop} для темы «{scope}»"
                )
                continue
            if const_name not in consts:
                problems.append(f"{js_path.name}: не найдена константа {const_name}")
                continue

            checked += 1
            if normalize(consts[const_name]) != normalize(css_value):
                problems.append(
                    f"{js_path.name}: {const_name} = {consts[const_name]!r}, "
                    f"а theme.css {css_prop} ({scope}) = {css_value!r}"
                )

    if problems:
        print("Расхождение токенов темы:\n", file=sys.stderr)
        for p in problems:
            print(f"  • {p}", file=sys.stderr)
        print(
            "\nJS перебивает CSS инлайном с !important — значит применится "
            "значение из JS, а theme.css будет вводить в заблуждение.\n"
            "Приведите оба места к одному значению.",
            file=sys.stderr,
        )
        return 1

    print(f"Токены темы совпадают: сверено {checked} значений в {len(THEME_JS)} JS-файлах.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
