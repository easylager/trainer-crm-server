"""
Ruble **amount display** for plain text (Telegram HTML, API error strings, digest).

ISO 4217 ``BYN`` remains in JSON ``currency``, DB columns, and OpenAPI. Configure human suffix via
``Settings.byr_display_sign`` (env ``BYR_DISPLAY_SIGN``), e.g. ``Br`` for a shorter Latin label.

TASK-043: both functions take an optional ``currency`` (default ``"BYN"``, so every existing call
keeps its exact prior output). Pass ``"RUB"`` for a RU-city trainer/client — resolved via
``src.shared.currency`` — to show the ruble sign (₽) instead. Names keep the historical "byn" for
now (see TASK-043 DEC-001 on not renaming widely-used identifiers without a concrete need).
"""
from __future__ import annotations

_byr_sign_cache: str | None = None

_CURRENCY_DISPLAY_SUFFIX: dict[str, str] = {
    "RUB": "₽",
}


def _resolve_byr_display_sign() -> str:
    """Cached suffix for f-strings; never empty."""
    global _byr_sign_cache
    if _byr_sign_cache is not None:
        return _byr_sign_cache
    try:
        from src.shared.config import Settings

        s = (Settings().byr_display_sign or "BYN").strip()
        _byr_sign_cache = s if s else "BYN"
    except Exception:
        _byr_sign_cache = "BYN"
    return _byr_sign_cache


def __getattr__(name: str):
    if name == "BYR_SIGN":
        import sys

        val = _resolve_byr_display_sign()
        setattr(sys.modules[__name__], "BYR_SIGN", val)
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _resolve_display_suffix(currency: str) -> str:
    if currency == "BYN":
        return _resolve_byr_display_sign()
    return _CURRENCY_DISPLAY_SUFFIX.get(currency, currency)


def format_rubles_byn_display(byn: float | int, currency: str = "BYN") -> str:
    """Whole or fractional amount + currency suffix (BYN uses the configured display sign)."""
    sign = _resolve_display_suffix(currency)
    x = float(byn)
    if x == int(x):
        return f"{int(x)} {sign}"
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return f"{s} {sign}"


def format_kopeks_byn_display(cents: int, currency: str = "BYN") -> str:
    """Kopecks → rubles string with comma kopecks when needed (digest / receipts style)."""
    sign = _resolve_display_suffix(currency)
    if int(cents) <= 0:
        return f"0 {sign}"
    rubles, kop = divmod(int(cents), 100)
    if kop == 0:
        return f"{rubles} {sign}"
    return f"{rubles},{kop:02d} {sign}"
