"""AC-006: ingest loop lives on the notification worker, not the API process."""
from __future__ import annotations

import inspect
from pathlib import Path

import src.bot.notification_service as notification_service


ROOT = Path(__file__).resolve().parents[2]


def test_notification_service_creates_ingest_scheduler_task() -> None:
    source = inspect.getsource(notification_service.main)
    assert "run_ice_ingest_scheduler_loop" in source
    assert "asyncio.create_task" in source


def test_ingest_loop_is_importable_from_worker_entrypoint() -> None:
    from src.ingestion.loop import run_ice_ingest_scheduler_loop

    assert inspect.iscoroutinefunction(run_ice_ingest_scheduler_loop)


def test_scheduler_is_absent_from_fastapi_and_webapp() -> None:
    app_src = (ROOT / "src/api/app.py").read_text(encoding="utf-8")
    webapp_src = (ROOT / "src/api/routes/webapp.py").read_text(encoding="utf-8")
    for blob in (app_src, webapp_src):
        assert "IceIngestScheduler" not in blob
        assert "run_ice_ingest_scheduler_loop" not in blob
        assert "ice_ingest" not in blob
