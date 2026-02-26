"""
Storage: S3 (presigned or proxy) or local dir when S3 not configured.
Photos resized on upload: main 800px, list thumb 320px (JPEG 82%/80%) for faster catalog.
"""
import io
import uuid
from pathlib import Path

from src.shared.config import Settings

PHOTO_MAIN_MAX_SIZE = 800
PHOTO_LIST_MAX_SIZE = 320
PHOTO_MAIN_QUALITY = 82
PHOTO_LIST_QUALITY = 80


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


def _resize_image(body: bytes, content_type: str, max_size: int, quality: int) -> bytes | None:
    """Resize to max_size (longest side), JPEG quality. Returns bytes or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    if w <= max_size and h <= max_size and content_type and "jpeg" in content_type.lower():
        return body
    if w > h:
        nw, nh = max_size, max(1, int(h * max_size / w))
    else:
        nw, nh = max(1, int(w * max_size / h)), max_size
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def upload_photo(trainer_id: int, body: bytes, content_type: str) -> tuple[str, str | None]:
    """Save photo: resize (800px main, 320px list), then S3 or local. Returns (file_key, file_key_list)."""
    main_bytes = _resize_image(body, content_type or "", PHOTO_MAIN_MAX_SIZE, PHOTO_MAIN_QUALITY) or body
    list_bytes = _resize_image(main_bytes, "image/jpeg", PHOTO_LIST_MAX_SIZE, PHOTO_LIST_QUALITY)
    ext = _ext_from_content_type(content_type) or ".jpg"
    base = f"trainers/{trainer_id}/{uuid.uuid4().hex}"
    file_key = base + ext
    file_key_list = (base + "_list.jpg") if (list_bytes and list_bytes != main_bytes) else None

    settings = Settings()
    ct = "image/jpeg"
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        (root / file_key).parent.mkdir(parents=True, exist_ok=True)
        (root / file_key).write_bytes(main_bytes)
        if file_key_list and list_bytes:
            (root / file_key_list).write_bytes(list_bytes)
        return file_key, file_key_list
    client = _get_client()
    client.put_object(Bucket=settings.s3_bucket, Key=file_key, Body=main_bytes, ContentType=ct)
    if file_key_list and list_bytes:
        client.put_object(Bucket=settings.s3_bucket, Key=file_key_list, Body=list_bytes, ContentType=ct)
    return file_key, file_key_list


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
