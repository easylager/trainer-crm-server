"""Public API (no auth): active trainers catalog and photo serving for client/bot."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.application.trainer_use_cases import list_active_trainers_for_client
from src.infrastructure import s3

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/trainers")
async def list_active_trainers(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, list]:
    """Active trainers with profile, photos, service_ids for client channel."""
    items = await list_active_trainers_for_client(session, limit=limit)
    return {"items": items}


@router.get("/photos/{file_key:path}")
async def serve_photo(file_key: str) -> Response:
    """Serve photo from S3 or local storage. URL = API_BASE_URL + /api/public/photos/ + file_key."""
    result = s3.get_photo(file_key)
    if not result:
        raise HTTPException(status_code=404, detail="Not found")
    body, content_type = result
    return Response(content=body, media_type=content_type)
