#!/usr/bin/env python3
"""TASK-389: медианы и p90 переключения вкладок по строкам лога `client tab-timing`.

Строки пишет POST /api/webapp/client/tab-timing (src/api/routes/webapp_client_tab_timing.py).
Откуда брать лог: `railway logs --service <web> > tab.log` (или любой файл/пайп со строками).

    python3 scripts/tab_timing_report.py tab.log
    railway logs ... | python3 scripts/tab_timing_report.py -
    python3 scripts/tab_timing_report.py tab.log --by platform,to --kind tab

Группы по умолчанию: kind, to, platform. Колонки: n, медиана, p90, медиана page_ms.
Ключи группировки: kind, from, to, platform, season_ui, nav.
"""

from __future__ import annotations

import argparse
import math
import re
import statistics
import sys
from collections import defaultdict

_LINE = re.compile(r"client tab-timing (?P<kv>(?:\w+=\S+\s*)+)")
_KEYS = ("kind", "from", "to", "platform", "season_ui", "nav")


def parse_line(line: str) -> dict[str, str] | None:
    m = _LINE.search(line)
    if not m:
        return None
    pairs = dict(p.split("=", 1) for p in m.group("kv").split())
    if "ms" not in pairs or "kind" not in pairs or "to" not in pairs:
        return None
    try:
        int(pairs["ms"])
        int(pairs.get("page_ms", pairs["ms"]))
    except ValueError:
        return None
    return pairs


def percentile(values: list[int], q: float) -> int:
    """Ближайший ранг: p90 по 10 значениям — девятое по возрастанию."""
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def summarize(rows: list[dict[str, str]], by: tuple[str, ...]) -> list[tuple[tuple[str, ...], int, int, int, int]]:
    groups: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(k, "-") for k in by)].append(row)
    out = []
    for key, items in sorted(groups.items()):
        ms = [int(r["ms"]) for r in items]
        page = [int(r.get("page_ms", r["ms"])) for r in items]
        out.append((key, len(items), int(statistics.median(ms)), percentile(ms, 0.9), int(statistics.median(page))))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="файл с логом или - для stdin")
    ap.add_argument("--by", default="kind,to,platform", help="ключи группировки через запятую")
    ap.add_argument("--kind", choices=("tab", "cold"), help="только переходы или только холодный старт")
    args = ap.parse_args(argv)
    by = tuple(k.strip() for k in args.by.split(",") if k.strip())
    bad = [k for k in by if k not in _KEYS]
    if bad:
        ap.error(f"неизвестные ключи: {', '.join(bad)}; доступны: {', '.join(_KEYS)}")
    stream = sys.stdin if args.log == "-" else open(args.log, encoding="utf-8", errors="replace")
    with stream:
        rows = [r for r in map(parse_line, stream) if r and (not args.kind or r["kind"] == args.kind)]
    if not rows:
        print("Нет строк `client tab-timing`.", file=sys.stderr)
        return 1
    print("\t".join([*by, "n", "median_ms", "p90_ms", "median_page_ms"]))
    for key, n, med, p90, page in summarize(rows, by):
        print("\t".join([*key, str(n), str(med), str(p90), str(page)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
