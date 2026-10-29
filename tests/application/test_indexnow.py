"""IndexNow: ключ-файл, отправка, дедуп, триггер только по изменению. Сети нет: httpx.MockTransport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.routes.indexnow_key import build_indexnow_key_router
from src.application import indexnow
from src.shared.config import Settings

KEY = "0123456789abcdef0123456789abcdef"
BASE = "https://glideclub.by"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    indexnow._reset_dedup()
    monkeypatch.setenv("WEBAPP_BASE_URL", BASE)
    yield
    indexnow._reset_dedup()


def _enable(monkeypatch, *, enabled=True, key: str | None = KEY):
    monkeypatch.setenv("INDEXNOW_ENABLED", "true" if enabled else "false")
    if key is None:
        monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    else:
        monkeypatch.setenv("INDEXNOW_KEY", key)


def _mock(status=200, calls=None, raises=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if raises:
            raise httpx.ConnectError("boom")
        if calls is not None:
            calls.append(json.loads(request.content))
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_settings_defaults_off():
    assert Settings.model_fields["indexnow_enabled"].default is False
    assert Settings.model_fields["indexnow_key"].default is None


async def _get(router, path):
    app = FastAPI()
    if router is not None:
        app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


@pytest.mark.asyncio
async def test_key_endpoint_enabled(monkeypatch):
    _enable(monkeypatch)
    resp = await _get(build_indexnow_key_router(), f"/{KEY}.txt")
    assert resp.status_code == 200 and resp.text == KEY
    assert resp.headers["content-type"].startswith("text/plain")
    assert (await _get(build_indexnow_key_router(), "/" + "f" * 32 + ".txt")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,key", [(False, KEY), (True, None), (True, "short"), (True, "Z" * 32)])
async def test_key_endpoint_not_registered(monkeypatch, enabled, key):
    _enable(monkeypatch, enabled=enabled, key=key)
    router = build_indexnow_key_router()
    assert router is None
    assert (await _get(router, f"/{KEY}.txt")).status_code == 404




_APP_PROBE = """
import asyncio, httpx
from src.api.app import app
async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://t') as c:
        k = await c.get('/{key}.txt')
        r = await c.get('/robots.txt')
        s = await c.head('/sitemap.xml')
        o = await c.get('/{other}.txt')
        print('RESULT', k.status_code, k.text[:40].replace(' ', '_'), r.status_code, 'Sitemap:' in r.text, s.status_code, o.status_code)
asyncio.run(main())
"""


def _probe_real_app(enabled: str) -> str:
    """Реальное приложение собирается заново в отдельном процессе: ключ-роут регистрируется при импорте."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "TELEGRAM_BOT_TOKEN_CLIENT": "x", "TELEGRAM_BOT_TOKEN_TRAINER": "x"}
    env.update(INDEXNOW_ENABLED=enabled, INDEXNOW_KEY=KEY)
    code = _APP_PROBE.replace("{key}", KEY).replace("{other}", "f" * 32)
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    return next(line for line in out.stdout.splitlines() if line.startswith("RESULT"))


def test_real_app_key_route_enabled_does_not_shadow_other_routes():
    # ключ 200, robots 200 со своим Sitemap, sitemap HEAD 200, чужой ключ 404
    assert _probe_real_app("true") == f"RESULT 200 {KEY} 200 True 200 404"


def test_real_app_key_route_absent_when_disabled():
    assert _probe_real_app("false").startswith("RESULT 404 ") and _probe_real_app("false").endswith(" 200 True 200 404")


@pytest.mark.asyncio
async def test_payload_and_key_location(monkeypatch):
    _enable(monkeypatch)
    calls: list = []
    n = await indexnow.submit_urls([f"{BASE}/c/minsk", f"{BASE}/p/minsk/a"], client=_mock(200, calls))
    assert n == 2
    assert calls == [
        {
            "host": "glideclub.by",
            "key": KEY,
            "keyLocation": f"{BASE}/{KEY}.txt",
            "urlList": [f"{BASE}/c/minsk", f"{BASE}/p/minsk/a"],
        }
    ]


@pytest.mark.asyncio
async def test_accepts_202(monkeypatch):
    _enable(monkeypatch)
    assert await indexnow.submit_urls([f"{BASE}/x"], client=_mock(202)) == 1


@pytest.mark.asyncio
async def test_batches_of_10000(monkeypatch):
    _enable(monkeypatch)
    calls: list = []
    urls = [f"{BASE}/p/c/{i}" for i in range(25_000)]
    assert await indexnow.submit_urls(urls, client=_mock(200, calls)) == 25_000
    assert [len(c["urlList"]) for c in calls] == [10_000, 10_000, 5_000]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,key", [(False, KEY), (True, None)])
async def test_flag_off_or_no_key_sends_nothing(monkeypatch, enabled, key):
    _enable(monkeypatch, enabled=enabled, key=key)
    calls: list = []
    assert await indexnow.submit_urls([f"{BASE}/x"], client=_mock(200, calls)) == 0
    assert calls == []


@pytest.mark.asyncio
async def test_dedup_within_hour_then_allowed(monkeypatch):
    _enable(monkeypatch)
    calls: list = []
    clock = [1000.0]
    monkeypatch.setattr(indexnow.time, "monotonic", lambda: clock[0])
    client = _mock(200, calls)
    url = f"{BASE}/c/minsk"
    assert await indexnow.submit_urls([url], client=client) == 1
    clock[0] += 3599
    assert await indexnow.submit_urls([url], client=client) == 0
    assert len(calls) == 1
    clock[0] += 2
    assert await indexnow.submit_urls([url], client=client) == 1
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_failed_send_is_not_marked_as_sent(monkeypatch):
    _enable(monkeypatch)
    url = f"{BASE}/c/minsk"
    assert await indexnow.submit_urls([url], client=_mock(500)) == 0
    calls: list = []
    assert await indexnow.submit_urls([url], client=_mock(200, calls)) == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_errors_swallowed(monkeypatch):
    _enable(monkeypatch)
    assert await indexnow.submit_urls([f"{BASE}/a"], client=_mock(raises=True)) == 0
    assert await indexnow.submit_urls([f"{BASE}/b"], client=_mock(429)) == 0


# ---- триггер: публикатор пингует только при реальном изменении набора сеансов ----


class _Publisher:
    @staticmethod
    def make(existing, drafts_keys):
        from datetime import datetime, timezone

        from src.ingestion import publish as pub
        from src.ingestion.publish_diff import ExistingParserSession

        class FakeNested:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class FakeResult:
            def mappings(self):
                return []

        class FakeSession:
            async def execute(self, *a, **k):
                return FakeResult()

            def begin_nested(self):
                return FakeNested()

        p = pub.SqlAlchemyIceSessionPublisher(FakeSession())

        async def load(arena_id, window):
            return existing

        async def noop(*a, **k):
            return None

        p._load_existing = load
        p._delete_ids = noop
        p._update = noop
        p._insert = noop
        return p


@pytest.mark.asyncio
async def test_publisher_pings_only_on_change(monkeypatch):
    from datetime import time, timedelta

    from src.ingestion import publish as pub
    from src.ingestion.publish_diff import ExistingParserSession
    from tests.ingestion.test_publish_stable_ids import _FINISHED, _TODAY, _draft, _at

    sent: list[int] = []

    async def fake_notify(session, arena_id):
        sent.append(arena_id)

    monkeypatch.setattr(indexnow, "notify_arena_changed", fake_notify)
    monkeypatch.setattr(pub, "assert_can_replace_ice_sessions", lambda run, run_id: None)

    from types import SimpleNamespace

    from src.ingestion.types import RUN_STATUS_OK

    run = SimpleNamespace(
        status=RUN_STATUS_OK,
        finished_at=_FINISHED,
        publish_timezone="Europe/Minsk",
        publish_horizon_days=14,
        arena_id=7,
    )
    day = _TODAY + timedelta(days=1)
    draft = _draft(7, day, time(10, 0))
    same = ExistingParserSession(id=1, starts_at_utc=draft.starts_at_utc, kind=draft.kind)

    # Прогон без изменений набора сеансов (только UPDATE на месте): пинга нет.
    p = _Publisher.make([same], [draft])
    assert await p.publish(run, [draft], run_id=1) == 1
    assert sent == []

    # Появился новый слот: пинг.
    p = _Publisher.make([], [draft])
    await p.publish(run, [draft], run_id=1)
    assert sent == [7]

    # Слот исчез из источника: пинг.
    gone = ExistingParserSession(id=2, starts_at_utc=_at(day, time(18, 0)), kind=draft.kind)
    p = _Publisher.make([same, gone], [draft])
    await p.publish(run, [draft], run_id=1)
    assert sent == [7, 7]


@pytest.mark.asyncio
async def test_notify_noop_when_disabled(monkeypatch):
    _enable(monkeypatch, enabled=False)

    class Boom:
        def begin_nested(self):
            raise AssertionError("must not touch DB when disabled")

    await indexnow.notify_arena_changed(Boom(), 1)


@pytest.mark.asyncio
async def test_notify_swallows_errors_and_schedules_task(monkeypatch):
    _enable(monkeypatch)

    class BadSession:
        def begin_nested(self):
            raise RuntimeError("db down")

    await indexnow.notify_arena_changed(BadSession(), 1)  # не бросает

    sent: list = []

    async def fake_urls(session, arena_id):
        return [f"{BASE}/c/minsk", f"{BASE}/p/minsk/a"]

    async def fake_submit(urls, **kw):
        sent.append(urls)
        return len(urls)

    class OkNested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class OkSession:
        def begin_nested(self):
            return OkNested()

    monkeypatch.setattr(indexnow, "arena_page_urls", fake_urls)
    monkeypatch.setattr(indexnow, "submit_urls", fake_submit)
    monkeypatch.setattr(indexnow, "NOTIFY_DELAY_SECONDS", 0.0)
    await indexnow.notify_arena_changed(OkSession(), 1)
    await asyncio.gather(*list(indexnow._background))
    assert sent == [[f"{BASE}/c/minsk", f"{BASE}/p/minsk/a"]]
