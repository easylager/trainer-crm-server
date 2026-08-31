#!/usr/bin/env python3
"""
Единая версия статических ассетов мини-аппов (TASK-017, AC-002, DEC-004).

Зачем. `/static/webapp` и большинство роутов `/webapp/*` отдаются с
`Cache-Control: public, max-age=31536000, immutable`, когда в URL есть `?v=`.
Инвалидация возможна только сменой версии. При этом часть файлов (оба theme-JS,
mini-app-trainer-theme.css, mini-app-client-theme.css) всегда отдаётся no-cache,
то есть доезжает мгновенно.

Из этой асимметрии следует главное: при частичном бампе у пользователя окажется
новый JS поверх старого закэшированного CSS — сломанная палитра, а не «старый
вид». Поэтому версия у всех ассетов общая и меняется одной командой.

Использование:
    python3 scripts/bump_webapp_assets.py --check     # все ли на одной версии
    python3 scripts/bump_webapp_assets.py --dry-run   # что изменится
    python3 scripts/bump_webapp_assets.py             # применить
    python3 scripts/bump_webapp_assets.py --version 202609010

Коды возврата: 0 — успех (для --check: версия единая), 1 — расхождение версий
при --check, 2 — ошибка ввода-вывода.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEBAPP = REPO / "static" / "webapp"

# Версионируем только локальные css/js. Внешние ссылки (шрифты, telegram SDK)
# не наши и версии не несут.
REF_RE = re.compile(
    r'(?P<attr>\b(?:href|src)=")(?P<path>[^"?#>]+\.(?:css|js))(?P<query>\?[^"#>]*)?(?P<rest>[^"]*)"'
)


def is_local(path: str) -> bool:
    return not (path.startswith(("http://", "https://", "//", "data:")))


def iter_html() -> list[Path]:
    return sorted(WEBAPP.glob("*.html"))


def current_versions() -> Counter:
    seen: Counter = Counter()
    for html in iter_html():
        text = html.read_text(encoding="utf-8")
        for m in REF_RE.finditer(text):
            if not is_local(m.group("path")):
                continue
            query = m.group("query") or ""
            found = re.search(r"[?&]v=([^&]*)", query)
            seen[found.group(1) if found else "<без версии>"] += 1
    return seen


def next_version() -> str:
    """Сегодняшняя дата плюс порядковый номер, следующий за уже занятым."""
    today = date.today().strftime("%Y%m%d")
    used = [
        v for v in current_versions() if v.startswith(today) and v[len(today) :].isdigit()
    ]
    suffixes = [int(v[len(today) :]) for v in used] or [0]
    return f"{today}{max(suffixes) + 1}"


def apply_version(text: str, version: str) -> tuple[str, int]:
    changed = 0

    def sub(m: re.Match) -> str:
        nonlocal changed
        path = m.group("path")
        if not is_local(path):
            return m.group(0)

        query = m.group("query") or ""
        # Сохраняем прочие query-параметры, заменяем только v=.
        params = [p for p in query.lstrip("?").split("&") if p and not p.startswith("v=")]
        params.append(f"v={version}")
        new_query = "?" + "&".join(params)

        replacement = f'{m.group("attr")}{path}{new_query}{m.group("rest")}"'
        if replacement != m.group(0):
            changed += 1
        return replacement

    return REF_RE.sub(sub, text), changed


def cmd_check() -> int:
    seen = current_versions()
    if not seen:
        print("Не найдено ни одной локальной ссылки на css/js.", file=sys.stderr)
        return 2

    total = sum(seen.values())
    if len(seen) == 1:
        only = next(iter(seen))
        if only == "<без версии>":
            print(f"Все {total} ссылок без версии — атомарность не обеспечена.", file=sys.stderr)
            return 1
        print(f"Версия единая: {only} ({total} ссылок).")
        return 0

    print(f"Версии расходятся — {len(seen)} различных на {total} ссылок:", file=sys.stderr)
    for version, count in seen.most_common():
        print(f"  {count:>4}  {version}", file=sys.stderr)
    print(
        "\nПри выкате часть ассетов обновится, часть останется в immutable-кэше.\n"
        "Запустите без --check, чтобы свести всё к одной версии.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", help="задать версию явно (по умолчанию — дата и порядковый номер)")
    ap.add_argument("--check", action="store_true", help="только проверить единство версии")
    ap.add_argument("--dry-run", action="store_true", help="показать изменения, не записывая")
    args = ap.parse_args()

    if not WEBAPP.is_dir():
        print(f"Нет каталога {WEBAPP}", file=sys.stderr)
        return 2

    if args.check:
        return cmd_check()

    version = args.version or next_version()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        print(f"Недопустимая версия: {version!r}", file=sys.stderr)
        return 2

    touched_files = 0
    touched_refs = 0
    for html in iter_html():
        try:
            text = html.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"Не удалось прочитать {html.name}: {exc}", file=sys.stderr)
            return 2

        new_text, changed = apply_version(text, version)
        if changed:
            touched_files += 1
            touched_refs += changed
            if args.dry_run:
                print(f"  {html.name}: {changed} ссылок")
            else:
                html.write_text(new_text, encoding="utf-8")

    verb = "будет обновлено" if args.dry_run else "обновлено"
    print(f"Версия {version}: {verb} {touched_refs} ссылок в {touched_files} файлах.")
    if args.dry_run:
        print("Это пробный прогон, файлы не изменены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
