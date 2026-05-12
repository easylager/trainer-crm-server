"""
Graphic sign of the Belarusian ruble (НБРБ, Постановление Правления №25 от 27.01.2026).

Unicode: **U+20C5** *BELARUSIAN RUBLE SIGN* (proposal Unicode L2/2026-26089; Currency Symbols block).
ISO 4217 code ``BYN`` stays for APIs, DB ``currency`` columns, and OpenAPI — use ``BYR_SIGN`` only in user-visible strings.
"""
from __future__ import annotations

# Cyrillic Б with horizontal bar — single assigned currency glyph when fonts include it.
BYR_SIGN = "\u20c5"


def format_rubles_byn_display(byn: float | int) -> str:
    """Format whole or fractional rubles with the graphic sign (no ISO suffix)."""
    x = float(byn)
    if x == int(x):
        return f"{int(x)} {BYR_SIGN}"
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return f"{s} {BYR_SIGN}"


def format_kopeks_byn_display(cents: int) -> str:
    """Kopecks → rubles string with comma kopecks when needed (digest / receipts style)."""
    if int(cents) <= 0:
        return f"0 {BYR_SIGN}"
    rubles, kop = divmod(int(cents), 100)
    if kop == 0:
        return f"{rubles} {BYR_SIGN}"
    return f"{rubles},{kop:02d} {BYR_SIGN}"
