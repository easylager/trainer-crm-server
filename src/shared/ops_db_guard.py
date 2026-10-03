"""Refuse cloud/prod database URLs unless the operator explicitly acknowledges it.

Ops seed/load/ingest scripts share this guard. Default is local-only.
``--i-know-this-is-prod`` sets allow_prod=True for a one-shot Railway write.
"""
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

LOCAL_DB_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "postgres", "db", "host.docker.internal"}
)
CLOUD_DB_MARKERS = (
    "railway",
    "supabase",
    "neon.tech",
    "amazonaws.com",
    "azure",
    "render.com",
    "onrender.com",
    "planetscale",
    "digitalocean",
    "prod.",
    "production",
)
ALLOWED_APPLY_DB_NAMES = frozenset({"trainer_crm_test", "trainer_crm"})
I_KNOW_THIS_IS_PROD = "--i-know-this-is-prod"


class ProdDatabaseError(RuntimeError):
    """Refuses writes against a non-local / production-looking URL."""


def normalize_db_url(url: str) -> str:
    raw = url.strip()
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
    ):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix) :]
    return raw


def async_database_url(url: str) -> str:
    """``create_async_engine`` needs ``postgresql+asyncpg://`` (not psycopg/psycopg2)."""
    base = normalize_db_url(url)
    if base.startswith("postgresql://"):
        return "postgresql+asyncpg://" + base[len("postgresql://") :]
    if "+asyncpg" in url:
        return url.strip()
    raise ProdDatabaseError(f"Unsupported DATABASE_URL scheme for async SQLAlchemy: {url!r}")


def add_i_know_this_is_prod_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        I_KNOW_THIS_IS_PROD,
        action="store_true",
        dest="i_know_this_is_prod",
        help=(
            "Permit this script against a cloud/Railway DATABASE_URL. "
            "Without it, cloud hosts are refused. Still requires --apply to write "
            "(except one-shot ingest, which always writes)."
        ),
    )


def warn_prod_ack() -> None:
    print(
        "WARNING: proceeding against a cloud/prod DATABASE_URL "
        f"because {I_KNOW_THIS_IS_PROD} was set.",
        file=sys.stderr,
    )


def assert_railway_target_database(url: str) -> None:
    """``--i-know-this-is-prod`` must target cloud Postgres, not dev localhost."""
    parsed = urlparse(normalize_db_url(url))
    host = (parsed.hostname or "").lower()
    local_ok = host in LOCAL_DB_HOSTS or (host.startswith("127.") and host.count(".") == 3)
    if local_ok:
        raise ProdDatabaseError(
            "DATABASE_URL points at localhost, but --i-know-this-is-prod expects Railway/cloud "
            "Postgres. Copy DATABASE_PUBLIC_URL from Railway into DATABASE_URL for this run "
            "(or prefix the ingest command with DATABASE_URL=...); do not commit the URL."
        )


def assert_database_url(
    url: str,
    *,
    apply: bool,
    allow_prod: bool = False,
    allowed_apply_db_names: frozenset[str] = ALLOWED_APPLY_DB_NAMES,
) -> None:
    if allow_prod:
        return
    parsed = urlparse(normalize_db_url(url))
    host = (parsed.hostname or "").lower()
    haystack = f"{host} {url.lower()}"
    if any(marker in haystack for marker in CLOUD_DB_MARKERS):
        raise ProdDatabaseError(f"refusing cloud/prod database host {host!r}")
    local_ok = host in LOCAL_DB_HOSTS or (host.startswith("127.") and host.count(".") == 3)
    if not local_ok:
        raise ProdDatabaseError(f"refusing non-local database host {host!r}")
    if not apply:
        return
    dbname = (parsed.path or "").lstrip("/").split("?")[0]
    if dbname not in allowed_apply_db_names:
        raise ProdDatabaseError(
            f"apply is limited to {sorted(allowed_apply_db_names)}, got {dbname!r}"
        )
