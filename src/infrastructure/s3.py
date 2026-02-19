"""
Storage: S3 (presigned or proxy) or local dir when S3 not configured.
"""
import uuid
from pathlib import Path

from src.shared.config import Settings


def _use_local() -> bool:
    s = Settings()
    return (
        not all([s.s3_endpoint, s.s3_access_key, s.s3_secret_key])
        and s.local_storage_path
    )


def _ext_from_content_type(ct: str) -> str | None:
    if not ct:
        return None
    ct = ct.lower()
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    return None


def upload_photo(trainer_id: int, body: bytes, content_type: str) -> str:
    """
    Save photo: to S3 if configured, else to local_storage_path (same file_key format).
    """
    ext = _ext_from_content_type(content_type) or ".jpg"
    file_key = f"trainers/{trainer_id}/{uuid.uuid4().hex}{ext}"
    settings = Settings()
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        path = root / file_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return file_key
    client = _get_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=file_key,
        Body=body,
        ContentType=content_type or "image/jpeg",
    )
    return file_key


def _get_client():
    settings = Settings()
    if not all([settings.s3_endpoint, settings.s3_access_key, settings.s3_secret_key]):
        raise RuntimeError("S3 not configured: set S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY")
    import boto3
    from botocore.config import Config
    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path" if settings.s3_path_style else "auto"},
    )
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=config,
        region_name=settings.s3_region,
    )


def get_photo(file_key: str) -> tuple[bytes, str] | None:
    """
    Read photo by file_key from S3 or local storage. Returns (body, content_type) or None.
    Only keys under trainers/ are allowed (no path traversal).
    """
    if not file_key.startswith("trainers/") or ".." in file_key:
        return None
    settings = Settings()
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        path = root / file_key
        if not path.is_file():
            return None
        body = path.read_bytes()
        ext = path.suffix.lower()
        content_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
        return body, content_type
    client = _get_client()
    try:
        resp = client.get_object(Bucket=settings.s3_bucket, Key=file_key)
        body = resp["Body"].read()
        content_type = resp.get("ContentType") or "image/jpeg"
        return body, content_type
    except Exception:
        return None


def presign_upload_url(
    trainer_id: int,
    content_type: str = "image/jpeg",
    expires_in: int = 3600,
) -> tuple[str, str]:
    """
    Presigned PUT URL for direct upload to S3. Not supported when using local storage.
    Returns (upload_url, file_key).
    """
    if _use_local():
        raise RuntimeError("Presign only with S3. Use POST /api/upload/photo for local storage.")
    settings = Settings()
    ext = _ext_from_content_type(content_type) or ".jpg"
    file_key = f"trainers/{trainer_id}/{uuid.uuid4().hex}{ext}"
    client = _get_client()
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": file_key,
            "ContentType": content_type or "image/jpeg",
        },
        ExpiresIn=expires_in,
    )
    return url, file_key
