"""FastAPI app: health check and API routers. No business logic here."""
from fastapi import FastAPI

from src.api.routes import public_router, trainers_router, upload_router

app = FastAPI(title="Trainer CRM API")

@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check for deployments."""
    return {"status": "ok"}

app.include_router(public_router)
app.include_router(trainers_router)
app.include_router(upload_router)
