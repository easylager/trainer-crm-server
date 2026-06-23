"""Upload: presign URL, multipart upload, photo registration by file_key.

Legacy routes require INTERNAL_UPLOAD_API_KEY (header X-Internal-Upload-Key) when set in env.
Production: leave unset to disable; trainers use Mini App endpoints with initData instead.
"""
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.schemas import PhotoRegisterBody, PresignBody
from src.application.trainer_use_cases import (
    TrainerPhotoFileKeyError,
    register_photo,
    upload_trainer_photo_from_bytes,
)
from src.infrastructure import s3
from src.shared.config import Settings

router = APIRouter(prefix="/api", tags=["upload"])


def _require_internal_upload_key(
    x_internal_upload_api_key: str | None = Header(None, alias="X-Internal-Upload-Key"),
) -> None:
    expected = Settings().internal_upload_api_key
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Legacy upload API is disabled. Use Web App photo upload with Telegram initData.",
        )
    if not x_internal_upload_api_key or x_internal_upload_api_key != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Internal-Upload-Key")


@router.post("/upload/photo/presign")
async def presign(
    body: PresignBody,
    _auth: None = Depends(_require_internal_upload_key),
) -> dict[str, str]:
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
    _auth: None = Depends(_require_internal_upload_key),
) -> dict[str, str]:
    """Register already-uploaded photo by file_key (e.g. after presigned upload)."""
    try:
        ok = await register_photo(session, trainer_id, body.file_key)
    except TrainerPhotoFileKeyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return {"file_key": body.file_key}


@router.post("/upload/photo")
async def upload_and_register(
    trainer_id: int = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(_require_internal_upload_key),
) -> dict[str, str]:
    """Upload file to S3/local (resized), add to trainer_photos. Returns file_key (and file_key_list if thumb generated)."""
    content_type = file.content_type or "image/jpeg"
    ok, err, file_key, file_key_list = await upload_trainer_photo_from_bytes(
        session, trainer_id, await file.read(), content_type
    )
    if not ok:
        if err == "too_large":
            raise HTTPException(status_code=413, detail="File too large")
        if err == "not_image":
            raise HTTPException(status_code=400, detail="Not a valid image")
        if err == "storage":
            raise HTTPException(status_code=503, detail="Storage temporarily unavailable")
        raise HTTPException(status_code=404, detail="Trainer not found")
    out: dict[str, str] = {"file_key": file_key or ""}
    if file_key_list:
        out["file_key_list"] = file_key_list
    return out


@router.post("/upload/legal")
async def upload_legal_document(
    file: UploadFile = File(...),
    _auth: None = Depends(_require_internal_upload_key),
) -> dict[str, str]:
    """
    Admin: upload legal document file (HTML/PDF/text) to S3/local under 'legal/' prefix.
    Returns file_key that can be used in legal_documents.file_key.

    Requires INTERNAL_UPLOAD_API_KEY (dev/scripts only; unset in production).
    """
    content_type = file.content_type or "application/octet-stream"
    body = await file.read()
    try:
        file_key = s3.upload_legal_document(body, content_type)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"file_key": file_key}
