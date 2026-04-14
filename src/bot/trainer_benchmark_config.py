"""
Trainer bot performance benchmarks. Configured once from trainer_app via Settings.

Env (via Settings): TRAINER_BOT_BENCHMARK_LOG, TRAINER_BOT_BENCHMARK_SLOW_MS

Grep production logs for prefix ``BENCH trainer_`` (logger ``trainer_bot.bench``).
"""
from __future__ import annotations

# Set by configure(); read-only for middleware.
log_every_update: bool = False
slow_total_ms: float | None = None


def configure(*, log_every_update: bool, slow_total_ms: int | None) -> None:
    """Call from trainer_app before polling starts."""
    globals()["log_every_update"] = log_every_update
    globals()["slow_total_ms"] = float(slow_total_ms) if slow_total_ms is not None else None


def is_active() -> bool:
    return log_every_update or slow_total_ms is not None


def log_inner_phases() -> bool:
    """DB/menu phase timings (noisy); only when full update logging is on."""
    return log_every_update


def is_slow_total(ms: float) -> bool:
    return slow_total_ms is not None and ms >= slow_total_ms
