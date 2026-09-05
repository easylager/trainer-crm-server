"""
Storage: S3 (presigned or proxy) or local dir when S3 not configured.
Photos resized on upload: main 800px, list thumb 320px (JPEG 82%/80%) for faster catalog.
"""
import io
import posixpath
import uuid
from pathlib import Path

from src.shared.config import Settings

PHOTO_MAIN_MAX_SIZE = 800
PHOTO_LIST_MAX_SIZE = 320
PHOTO_HERO_MAX_SIZE = 1600
COLLECTIVE_LOGO_MAX_SIZE = 400
COLLECTIVE_COVER_MAX_SIZE = 1600
COLLECTIVE_GALLERY_MAX_SIZE = 800
PHOTO_MAIN_QUALITY = 82
PHOTO_LIST_QUALITY = 80
PHOTO_CACHE_CONTROL = "public, max-age=31536000, immutable"


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
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=file_key,
        Body=main_bytes,
        ContentType=ct,
        CacheControl=PHOTO_CACHE_CONTROL,
    )
    if file_key_list and list_bytes:
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=file_key_list,
            Body=list_bytes,
            ContentType=ct,
            CacheControl=PHOTO_CACHE_CONTROL,
        )
    return file_key, file_key_list


def upload_arena_photo(arena_id: int, body: bytes, content_type: str) -> dict:
    """Save arena photo as JPEG thumb (~320), card (~800), hero (~1600). Returns keys + pixel size."""
    hero_bytes = _resize_image(body, content_type or "", PHOTO_HERO_MAX_SIZE, PHOTO_MAIN_QUALITY) or body
    card_bytes = _resize_image(hero_bytes, "image/jpeg", PHOTO_MAIN_MAX_SIZE, PHOTO_MAIN_QUALITY) or hero_bytes
    thumb_bytes = _resize_image(card_bytes, "image/jpeg", PHOTO_LIST_MAX_SIZE, PHOTO_LIST_QUALITY) or card_bytes
    width = height = None
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(body))
        width, height = img.size
    except Exception:
        pass
    base = f"arenas/{int(arena_id)}/{uuid.uuid4().hex}"
    variants = {
        "hero": f"{base}_hero.jpg",
        "card": f"{base}_card.jpg",
        "thumb": f"{base}_thumb.jpg",
    }
    payloads = {"hero": hero_bytes, "card": card_bytes, "thumb": thumb_bytes}
    settings = Settings()
    ct = "image/jpeg"
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        for kind, key in variants.items():
            path = root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payloads[kind])
        return {"storage_key": variants["hero"], "variants": variants, "width": width, "height": height}
    client = _get_client()
    for kind, key in variants.items():
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=payloads[kind],
            ContentType=ct,
            CacheControl=PHOTO_CACHE_CONTROL,
        )
    return {"storage_key": variants["hero"], "variants": variants, "width": width, "height": height}


def upload_collective_image(
    collective_id: int,
    body: bytes,
    content_type: str,
    *,
    kind: str,
) -> str:
    """Save studio asset under collectives/{id}/ — logo, cover, or gallery."""
    kind_norm = (kind or "gallery").strip().lower()
    if kind_norm not in ("logo", "cover", "gallery"):
        kind_norm = "gallery"
    max_size = {
        "logo": COLLECTIVE_LOGO_MAX_SIZE,
        "cover": COLLECTIVE_COVER_MAX_SIZE,
        "gallery": COLLECTIVE_GALLERY_MAX_SIZE,
    }[kind_norm]
    main_bytes = _resize_image(body, content_type or "", max_size, PHOTO_MAIN_QUALITY) or body
    file_key = f"collectives/{collective_id}/{kind_norm}_{uuid.uuid4().hex}.jpg"
    settings = Settings()
    ct = "image/jpeg"
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        (root / file_key).parent.mkdir(parents=True, exist_ok=True)
        (root / file_key).write_bytes(main_bytes)
        return file_key
    client = _get_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=file_key,
        Body=main_bytes,
        ContentType=ct,
        CacheControl=PHOTO_CACHE_CONTROL,
    )
    return file_key


def upload_legal_document(body: bytes, content_type: str | None = None) -> str:
    """Upload legal document file to S3/local under legal/ prefix. Returns file_key."""
    settings = Settings()
    ext = ""
    ct = content_type or "application/octet-stream"
    # simple mapping for common types; others leave without extension
    c = ct.lower()
    if "html" in c:
        ext = ".html"
    elif "pdf" in c:
        ext = ".pdf"
    elif "plain" in c or "text" in c:
        ext = ".txt"
    file_key = f"legal/{uuid.uuid4().hex}{ext}"
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        path = root / file_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return file_key
    client = _get_client()
    client.put_object(Bucket=settings.s3_bucket, Key=file_key, Body=body, ContentType=ct)
    return file_key


def upload_certificate_file(body: bytes, trainer_id: int, certificate_id: int) -> str:
    """Upload certificate PDF to S3/local under certificates/{trainer_id}/{certificate_id}.pdf. Returns file_key."""
    file_key = f"certificates/{trainer_id}/{certificate_id}.pdf"
    ct = "application/pdf"
    settings = Settings()
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        path = root / file_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return file_key
    client = _get_client()
    client.put_object(Bucket=settings.s3_bucket, Key=file_key, Body=body, ContentType=ct)
    return file_key


def resolve_object_key_under_prefixes(
    file_key: str | None,
    allowed_prefixes: tuple[str, ...],
) -> str | None:
    """
    Normalize object key and ensure it stays under one of allowed_prefixes after path
    normalization (blocks e.g. trainers/../legal/doc or certificates/../trainers/x).
    """
    if not file_key or not isinstance(file_key, str):
        return None
    if "\x00" in file_key:
        return None
    s = file_key.replace("\\", "/")
    # Reject alternate spellings like certificates/../trainers/... (normpath would collapse to public key).
    if ".." in s:
        return None
    if s.startswith("/"):
        return None
    norm = posixpath.normpath(s)
    if norm in (".", "..") or norm.startswith("../"):
        return None
    if not norm or norm == ".":
        return None
    if ".." in norm.split("/"):
        return None
    for p in allowed_prefixes:
        if p and norm.startswith(p):
            return norm
    return None


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


def get_file(file_key: str, allowed_prefixes: tuple[str, ...] = ("trainers/",)) -> tuple[bytes, str] | None:
    """
    Read file by file_key from S3 or local storage. Returns (body, content_type) or None.
    allowed_prefixes: e.g. ("trainers/", "certificates/", "legal/") to restrict keys.
    """
    norm_key = resolve_object_key_under_prefixes(file_key, allowed_prefixes)
    if not norm_key:
        return None
    settings = Settings()
    if _use_local():
        root = Path(settings.local_storage_path).resolve()
        path = root / norm_key
        if not path.is_file():
            return None
        body = path.read_bytes()
        ext = path.suffix.lower()
        content_type = {
            ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".html": "text/html", ".txt": "text/plain",
        }.get(ext, "application/octet-stream")
        return body, content_type
    client = _get_client()
    try:
        resp = client.get_object(Bucket=settings.s3_bucket, Key=norm_key)
        body = resp["Body"].read()
        content_type = resp.get("ContentType") or "application/octet-stream"
        return body, content_type
    except Exception:
        return None


def get_photo(file_key: str) -> tuple[bytes, str] | None:
    """
    Read photo by file_key from S3 or local storage. Returns (body, content_type) or None.
    Allowed prefixes: trainers/, collectives/, arenas/.
    """
    return get_file(file_key, allowed_prefixes=("trainers/", "collectives/", "arenas/"))


def presign_get_url(file_key: str, expires_in: int | None = None) -> str | None:
    """
    Presigned GET URL for direct client download. Returns None when using local storage or on error.
    Only keys under trainers/ are allowed.
    """
    norm_key = resolve_object_key_under_prefixes(file_key, ("trainers/",))
    if not norm_key:
        return None
    if _use_local():
        return None
    settings = Settings()
    if expires_in is None:
        expires_in = settings.photo_presigned_expires_sec
    try:
        client = _get_client()
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": norm_key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception:
        return None


def presign_upload_url(
    trainer_id: int,
    content_type: str = "image/jpeg",
    expires_in: int | None = None,
) -> tuple[str, str]:
    """
    Presigned PUT URL for direct upload to S3. Not supported when using local storage.
    Key is always trainers/{trainer_id}/<uuid>.<ext> — no cross-trainer overwrite via URL alone.
    Returns (upload_url, file_key).
    """
    if _use_local():
        raise RuntimeError("Presign only with S3. Use POST /api/upload/photo for local storage.")
    settings = Settings()
    if expires_in is None:
        expires_in = settings.photo_upload_presign_expires_sec
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
