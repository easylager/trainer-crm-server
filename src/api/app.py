"""FastAPI app: health check and API routers. No business logic here."""
from fastapi import FastAPI, HTTPException

from sqlalchemy import text

from src.api.routes import public_router, trainers_router, upload_router
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings

app = FastAPI(title="Trainer CRM API")


@app.get("/health")
async def health() -> dict[str, str]:
    """
    Liveness + readiness: DB must be reachable for 200.
    Optional S3: reported as ok/skip/error; 503 only on DB failure.
    """
    result: dict[str, str] = {"status": "ok", "db": "ok"}

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"database unavailable: {e!s}",
        )

    settings = Settings()
    if settings.s3_endpoint and settings.s3_access_key and settings.s3_secret_key:
        try:
            from src.infrastructure.s3 import _get_client
            client = _get_client()
            client.head_bucket(Bucket=settings.s3_bucket)
            result["s3"] = "ok"
        except Exception:
            result["s3"] = "error"
    else:
        result["s3"] = "skip"

    return result


app.include_router(public_router)
app.include_router(trainers_router)
app.include_router(upload_router)
