"""
Pytest fixtures for integration and API tests.
Uses DATABASE_URL from env (or .env) — for tests point it to trainer_crm_test and run: alembic upgrade head

Never point DATABASE_URL at staging/production while running pytest: integration tests write trainers,
clients, slots, bookings, and would pollute user-facing catalog tables if misconfigured.

At session start we refuse remote/cloud DATABASE_URL unless PYTEST_ALLOW_REMOTE_DB=1 (escape hatch).
On allowed hosts we require database name trainer_crm_test unless PYTEST_RELAX_DATABASE_NAME=1.

Each test runs inside one DB connection + outer transaction that is **rolled back** after the test
(unless PYTEST_DISABLE_TRANSACTION_ROLLBACK=1). Application code may call session.commit(); changes stay
inside the outer transaction and never persist — see SQLAlchemy «join external transaction» / savepoints.

One engine + one outer transaction + one sessionmaker per test. API routes, raw ``db_session`` SQL,
and modules that did ``from src.infrastructure.db import async_session_factory`` (cached reference)
all see the same factory — otherwise HTTP writes are invisible to test SQL and ``notification_loops``
would use a stale factory / wrong connection.

``app.dependency_overrides[get_session]`` yields the same ``AsyncSession`` as ``db_session`` so
HTTP handlers never open a second session on the same asyncpg connection (asyncpg is strictly
single-flight per connection).
"""
import os
import uuid
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.app import app
from src.api.deps import get_session
from src.shared.config import Settings

_TEST_DB_NAME = "trainer_crm_test"


def _normalize_database_url_for_parse(url: str) -> str:
    u = url.strip()
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql+psycopg2://"):
        if u.startswith(prefix):
            return "postgresql://" + u[len(prefix) :]
    return u


def _assert_test_database_url_allowed() -> None:
    """
    Block pytest from using staging/production URLs by mistake.
    CI sets DATABASE_URL to localhost/trainer_crm_test — allowed.
    """
    if os.environ.get("PYTEST_ALLOW_REMOTE_DB", "").strip() == "1":
        return
    settings = Settings()
    raw = settings.database_url
    normalized = _normalize_database_url_for_parse(raw)
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lstrip("/")
    dbname = path.split("?")[0] if path else ""

    allowed_hosts = frozenset(
        {
            "localhost",
            "127.0.0.1",
            "::1",
            "postgres",
            "db",
            "host.docker.internal",
        }
    )
    local_ok = host in allowed_hosts or (host.startswith("127.") and host.count(".") == 3)

    haystack = f"{host} {raw.lower()}"
    blocked_markers = (
        "railway",
        "supabase",
        "neon.tech",
        "amazonaws.com",
        "azure",
        "render.com",
        "onrender.com",
        "planetscale",
        "digitalocean",
    )
    if any(m in haystack for m in blocked_markers):
        raise pytest.UsageError(
            "pytest refused DATABASE_URL: host looks like a managed/cloud database. "
            "Use Postgres on localhost (see docker-compose) with database "
            f"{_TEST_DB_NAME!r}, or set PYTEST_ALLOW_REMOTE_DB=1 only if you accept writing to that DB."
        )

    if not local_ok:
        raise pytest.UsageError(
            f"pytest refused DATABASE_URL host {host!r}: tests must run against local Postgres only. "
            f"Expected host in {sorted(allowed_hosts)!r} or 127.x.x.x, or set PYTEST_ALLOW_REMOTE_DB=1."
        )

    if os.environ.get("PYTEST_RELAX_DATABASE_NAME", "").strip() == "1":
        return
    if dbname != _TEST_DB_NAME:
        raise pytest.UsageError(
            f"pytest requires database name {_TEST_DB_NAME!r}, got {dbname or '(empty)'!r}. "
            "Create DB: `createdb trainer_crm_test` (or docker), run migrations, "
            "or set PYTEST_RELAX_DATABASE_NAME=1 to allow another name on localhost (not recommended)."
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    _assert_test_database_url_allowed()


def _apply_test_session_factory(factory):
    """
    Replace async_session_factory everywhere tests might resolve it.
    ``from pkg import async_session_factory`` binds the object at import time; patching only
    ``session`` module leaves ``db`` package and ``notification_loops`` pointing at the old maker.
    """
    import src.api.app as app_mod
    import src.bot.notification_loops as nl_mod
    import src.infrastructure.db as db_pkg
    import src.infrastructure.db.session as session_mod

    old = {
        "session": session_mod.async_session_factory,
        "db": db_pkg.async_session_factory,
        "app": app_mod.async_session_factory,
        "nl": nl_mod.async_session_factory,
    }
    session_mod.async_session_factory = factory
    db_pkg.async_session_factory = factory
    app_mod.async_session_factory = factory
    nl_mod.async_session_factory = factory
    return old


def _restore_test_session_factory(old: dict) -> None:
    import src.api.app as app_mod
    import src.bot.notification_loops as nl_mod
    import src.infrastructure.db as db_pkg
    import src.infrastructure.db.session as session_mod

    session_mod.async_session_factory = old["session"]
    db_pkg.async_session_factory = old["db"]
    app_mod.async_session_factory = old["app"]
    nl_mod.async_session_factory = old["nl"]


def _make_session_factory_with_rollback(conn):
    """
    Savepoints (join_transaction_mode) so application code can commit() inside tests;
    outer transaction rollback discards all changes.
    """
    try:
        return async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
    except TypeError:
        return None


def belarus_test_phone(telegram_id: int) -> tuple[str, str]:
    """
    Stable unique Belarus-shaped phone per telegram_id for tests.
    Avoids ix_clients_telegram_id / ix_clients_phone_normalized collisions when the DB is reused across tests.
    """
    nine = telegram_id % (10**9)
    normalized = f"375{nine:09d}"
    return f"+{normalized}", normalized


def unique_test_telegram_id() -> int:
    """
    Random Telegram-like id in a high range so integration/e2e tests do not collide
    with each other or with rows left from previous runs on a dev database.
    """
    return 6_000_000_000 + (uuid.uuid4().int % 999_999_999)


@pytest.fixture
async def _test_db_core() -> AsyncGenerator[dict, None]:
    """
    Single connection + sessionmaker + one open Session for the test body.
    Patches all async_session_factory bindings so ASGI handlers and notification_loops match db_session.

    FastAPI routes must use the same AsyncSession as tests: a second session from the same
    asyncpg connection causes «another operation is in progress» and teardown failures.
    """
    settings = Settings()
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
    )
    if os.environ.get("PYTEST_DISABLE_TRANSACTION_ROLLBACK", "").strip() == "1":
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        old = _apply_test_session_factory(factory)
        try:
            async with factory() as session:

                async def _override_get_session():
                    yield session

                app.dependency_overrides[get_session] = _override_get_session
                try:
                    yield {"session": session, "factory": factory, "engine": engine}
                finally:
                    app.dependency_overrides.pop(get_session, None)
        finally:
            _restore_test_session_factory(old)
            await engine.dispose()
        return

    async with engine.connect() as conn:
        trans = await conn.begin()
        factory = _make_session_factory_with_rollback(conn)
        if factory is None:
            await trans.rollback()
            await engine.dispose()
            raise pytest.UsageError(
                "This SQLAlchemy build has no join_transaction_mode=create_savepoint on async_sessionmaker. "
                "Upgrade sqlalchemy>=2.0.26 or set PYTEST_DISABLE_TRANSACTION_ROLLBACK=1 (writes will persist)."
            )
        old = _apply_test_session_factory(factory)
        try:
            async with factory() as session:

                async def _override_get_session():
                    yield session

                app.dependency_overrides[get_session] = _override_get_session
                try:
                    yield {"session": session, "factory": factory, "engine": engine, "trans": trans}
                finally:
                    app.dependency_overrides.pop(get_session, None)
        finally:
            _restore_test_session_factory(old)
            await trans.rollback()
    await engine.dispose()


@pytest.fixture
async def db_session(_test_db_core) -> AsyncGenerator[AsyncSession, None]:
    """Same DB transaction as patched FastAPI + notification_loops (see _test_db_core)."""
    yield _test_db_core["session"]


@pytest.fixture
async def app_use_test_db(_test_db_core) -> AsyncGenerator[None, None]:
    """Depends on _test_db_core; use with API tests that also need db_session for setup SQL."""
    yield


@pytest.fixture(autouse=True)
def _enable_trainer_collective_feature_for_marked_tests(request, monkeypatch) -> None:
    """Collective API/application tests assume TRAINER_COLLECTIVE_ENABLED=1."""
    if request.node.get_closest_marker("collective"):
        monkeypatch.setenv("TRAINER_COLLECTIVE_ENABLED", "1")
