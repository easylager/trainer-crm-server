"""Upload: presign URL, multipart upload, photo registration by file_key."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.schemas import PhotoRegisterBody, PresignBody
from src.application.trainer_use_cases import register_photo
from src.infrastructure import s3

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload/photo/presign")
async def presign(body: PresignBody) -> dict[str, str]:
    """Return presigned PUT URL for direct S3 upload. Fails if using local storage."""
    try:
        url, file_key = s3.presign_upload_url(body.trainer_id, content_type=body.content_type)
        return {"upload_url": url, "file_key": file_key}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trainers/{trainer_id}/photos")
async def register_photo_by_key(
    trainer_id: int,
    body: PhotoRegisterBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Register already-uploaded photo by file_key (e.g. after presigned upload)."""
    ok = await register_photo(session, trainer_id, body.file_key)
    if not ok:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return {"file_key": body.file_key}


@router.post("/upload/photo")
async def upload_and_register(
    trainer_id: int = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Upload file to S3/local (resized), add to trainer_photos. Returns file_key (and file_key_list if thumb generated)."""
    content_type = file.content_type or "image/jpeg"
    file_key, file_key_list = s3.upload_photo(trainer_id, await file.read(), content_type)
    ok = await register_photo(session, trainer_id, file_key, 0, file_key_list=file_key_list)
    if not ok:
        raise HTTPException(status_code=404, detail="Trainer not found")
    out: dict[str, str] = {"file_key": file_key}
    if file_key_list:
        out["file_key_list"] = file_key_list
    return out
