"""TASK-197: gzip weight of /webapp/ice and /webapp/catalog must not grow quietly.

The HTML names the assets. External fonts and the Telegram SDK are not ours.
Baselines are the gzip size (mtime=0, level 9) of the HTML plus each local css/js
it references, counted once. A page may shrink; growth past 5% fails CI.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_WEBAPP = _REPO / "static" / "webapp"
_ATTR = re.compile(r"""(?:src|href)=["']([^"']+)["']""", re.I)

# Gzip level 9, mtime 0. Re-measure after intentional UI growth (TASK-197 → TASK-222
# share sheet, then the «Зимой» list, the season reminder, TASK-243 copy keys,
# then the hub-language search page and the match share sheet; the share sheet now loads
# on demand on ice.html, which took the page back under its pre-epic size; then
# write-access.js and the booking write-access check on catalog.html, 2026-10-25;
# then the «Что ищем» sheet and ticket seats on the rink card, TASK-333, 2026-10-26;
# then «Тренеры» in «Поиске» and trainer taps → the trainers showcase, stage 1 of entries, 2026-11-08: ice.html +1.2 KB;
# re-measured with the trainer funnel (/t/ pages, TASK-356), 2026-11-08;
# catalog.html +5.4 KB: the «Я» tab and season flags in the client shell, «Твой сезон на льду», 2026-11-12;
# ice.html +12.6 KB: the season shell on «Поиск», tab press under the finger and tab-timing in the shell, fast-tabs, 2026-11-12;
# catalog.html +12.1 KB: hard entryGate + write-access.js on shell pages, 2026-11-15;
# ice.html +13.1 KB: KK site banner/pick styles landed in glide-components.css (shared by ice.html), 2026-11-20).
# A page may shrink; growth past +5% fails CI.
_BASELINE_GZIP = {
    "ice.html": 267_291,
    "catalog.html": 243_235,
}


def _local_assets(html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _ATTR.finditer(html):
        url = match.group(1).split("#", 1)[0]
        if url.startswith(("http://", "https://", "data:", "mailto:", "tel:", "viber:", "#")):
            continue
        path = url.split("?", 1)[0].lstrip("/")
        if path.startswith("webapp/"):
            path = path[len("webapp/") :]
        if not path.endswith((".js", ".css")):
            continue
        if path in seen:
            continue
        seen.add(path)
        found.append(path)
    return found


def _gzip_len(data: bytes) -> int:
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def page_gzip_bytes(html_name: str) -> int:
    html_path = _WEBAPP / html_name
    html = html_path.read_bytes()
    total = _gzip_len(html)
    for rel in _local_assets(html.decode()):
        # /static/shared/* отдаётся от корня репозитория, остальные css/js — из static/webapp.
        asset = (_REPO / rel) if rel.startswith("static/") else (_WEBAPP / rel)
        assert asset.is_file(), f"{html_name} references missing {rel}"
        total += _gzip_len(asset.read_bytes())
    return total


def test_ice_and_catalog_page_weight_stay_within_five_percent() -> None:
    for name, baseline in _BASELINE_GZIP.items():
        size = page_gzip_bytes(name)
        assert size * 20 <= baseline * 21, f"{name} gzip {size} bytes is more than 5% over the budget {baseline}"


# TASK-391: оболочка «Я» + «Записи» (флаг fast_tabs) — первый заход по адресу вкладки. Это та же страница,
# что без флага, плюс client-tabs.js (defer, ~7 КБ gzip) и две строки CSS; вторая вкладка приходит фрагментом
# потом, в простое или по нажатию. Замер 2026-11-12; bookings +6.7 KB — entryGate write-access.js, 2026-11-15.
# Рост больше 5% — падение.
_SHELL_BASELINE_GZIP = {
    "me": 173_336,
    "bookings": 131_225,
}


def _html_gzip_bytes(html: str) -> int:
    total = _gzip_len(html.encode())
    for rel in _local_assets(html):
        asset = (_REPO / rel) if rel.startswith("static/") else (_WEBAPP / rel)
        assert asset.is_file(), f"shell references missing {rel}"
        total += _gzip_len(asset.read_bytes())
    return total


def test_fast_tabs_shell_first_open_weight() -> None:
    from src.api.client_tabs_shell import page_html, shell_html

    router = _gzip_len((_WEBAPP / "client-tabs.js").read_bytes())
    for tab, baseline in _SHELL_BASELINE_GZIP.items():
        shell = _html_gzip_bytes(shell_html(tab))
        page = _html_gzip_bytes(page_html(tab))
        assert shell * 20 <= baseline * 21, f"{tab} shell gzip {shell} bytes is more than 5% over the budget {baseline}"
        # Кроме роутера оболочка на первом заходе ничего не качает: те же файлы, что страница без флага.
        assert shell - page <= router + 256, f"{tab} shell adds {shell - page} bytes over the page, router is {router}"


# TASK-232: открытка /zovi/{code} открывается из Threads и Instagram по мобильной сети.
# Шаблон с CSS внутри + свои JS (без токенов и шрифтов) — не больше 40 КБ gzip.
_ZOVI_CARD_BUDGET_GZIP = 40 * 1024


def test_zovi_card_page_weight_within_budget() -> None:
    template = _REPO / "static" / "share" / "zovi-card.html"
    total = _gzip_len(template.read_bytes())
    for name in ("zovi-model.js", "zovi-card.js"):
        total += _gzip_len((_REPO / "static" / "shared" / name).read_bytes())
    assert total <= _ZOVI_CARD_BUDGET_GZIP, f"zovi card gzip {total} bytes is over {_ZOVI_CARD_BUDGET_GZIP}"
