#!/usr/bin/env python3
"""
Dump production Postgres and upload to an off-site S3-compatible bucket.

Designed for GitHub Actions (scheduled) or manual run with env vars / .env.
Uses a dedicated BACKUP_S3_* bucket — not the app photo bucket.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv_if_present() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip().strip('"').strip("'")


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    if val is None or str(val).strip() == "":
        return None
    return str(val).strip()


def _sync_database_url() -> str:
    raw = _env("BACKUP_DATABASE_URL") or _env("DATABASE_URL_SYNC") or _env("DATABASE_URL")
    if not raw:
        raise SystemExit(
            "Set BACKUP_DATABASE_URL (recommended) or DATABASE_URL_SYNC for pg_dump."
        )
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
        "postgres+asyncpg://",
        "postgres+psycopg://",
    ):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix) :]
    return raw


def _s3_client():
    endpoint = _env("BACKUP_S3_ENDPOINT")
    access = _env("BACKUP_S3_ACCESS_KEY")
    secret = _env("BACKUP_S3_SECRET_KEY")
    region = _env("BACKUP_S3_REGION", "auto") or "auto"
    path_style = (_env("BACKUP_S3_PATH_STYLE", "true") or "true").lower() in ("1", "true", "yes")
    if not all([endpoint, access, secret]):
        raise SystemExit("Set BACKUP_S3_ENDPOINT, BACKUP_S3_ACCESS_KEY, BACKUP_S3_SECRET_KEY.")
    cfg = Config(signature_version="s3v4", s3={"addressing_style": "path" if path_style else "auto"})
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=region,
        config=cfg,
    )


def _assert_pg_dump_looks_valid(sql_path: Path) -> None:
    """Refuse to upload an empty or truncated dump (pg_dump can exit 0 and still write almost nothing)."""
    size = sql_path.stat().st_size
    if size < 1024:
        raise SystemExit("pg_dump output suspiciously small (<1 KB). Aborting upload.")
    head = sql_path.read_bytes()[:800].decode("utf-8", errors="replace")
    lowered = head.lower()
    if "postgresql database dump" not in lowered and "pg_dump" not in lowered:
        raise SystemExit("pg_dump output does not look like a PostgreSQL dump. Aborting upload.")


def _resolve_pg_dump() -> str:
    """
    Pick pg_dump binary. Ubuntu runners ship PG 16 in /usr/bin; Railway prod is PG 18+.
    Prefer BACKUP_PG_DUMP, then /usr/lib/postgresql/<major>/bin (PGDG), then highest major found.
    """
    explicit = _env("BACKUP_PG_DUMP")
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        raise SystemExit(f"BACKUP_PG_DUMP not found: {explicit}")

    preferred_major = (_env("BACKUP_PG_MAJOR", "18") or "18").strip()
    if preferred_major.isdigit():
        candidate = Path(f"/usr/lib/postgresql/{preferred_major}/bin/pg_dump")
        if candidate.is_file():
            return str(candidate)

    best: tuple[int, str] | None = None
    pg_root = Path("/usr/lib/postgresql")
    if pg_root.is_dir():
        for path in pg_root.glob("*/bin/pg_dump"):
            if not path.is_file():
                continue
            try:
                major = int(path.parent.parent.name)
            except ValueError:
                continue
            if best is None or major > best[0]:
                best = (major, str(path))
    if best:
        return best[1]

    found = shutil.which("pg_dump")
    if found:
        return found
    raise SystemExit(
        "pg_dump not found — install postgresql-client matching prod major "
        "(e.g. postgresql-client-18 on CI)."
    )


def _run_pg_dump(db_url: str, out_path: Path) -> None:
    pg_dump = _resolve_pg_dump()
    print(f"Using pg_dump: {pg_dump}")
    proc_version = subprocess.run([pg_dump, "--version"], capture_output=True, text=True)
    if proc_version.stdout:
        print(proc_version.stdout.strip())
    cmd = [
        pg_dump,
        "--no-owner",
        "--no-acl",
        "--format=plain",
        "--file",
        str(out_path),
        db_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout or "pg_dump failed\n")
        raise SystemExit(proc.returncode)


def _gzip_file(src: Path, dest: Path) -> None:
    with src.open("rb") as fin, gzip.open(dest, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)


def _upload(client, bucket: str, key: str, path: Path) -> int:
    size = path.stat().st_size
    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={"ContentType": "application/gzip", "Metadata": {"source": "trainer-crm-backup"}},
    )
    return size


def _prune_old_backups(client, bucket: str, prefix: str, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted = 0
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents") or []:
            lm = obj.get("LastModified")
            key = obj.get("Key")
            if not key or not lm:
                continue
            if lm.tzinfo is None:
                lm = lm.replace(tzinfo=UTC)
            if lm < cutoff:
                client.delete_object(Bucket=bucket, Key=key)
                deleted += 1
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return deleted


def main() -> None:
    _load_dotenv_if_present()
    db_url = _sync_database_url()
    bucket = _env("BACKUP_S3_BUCKET")
    if not bucket:
        raise SystemExit("Set BACKUP_S3_BUCKET (dedicated backups bucket).")
    prefix = (_env("BACKUP_S3_PREFIX", "postgres/") or "postgres/").lstrip("/")
    if not prefix.endswith("/"):
        prefix += "/"
    retention = int(_env("BACKUP_RETENTION_DAYS", "35") or "35")

    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    key = f"{prefix}{now.strftime('%Y/%m/%d')}/trainer_crm_{stamp}.sql.gz"

    with tempfile.TemporaryDirectory(prefix="trainer_crm_backup_") as tmp:
        tmp_dir = Path(tmp)
        sql_path = tmp_dir / "dump.sql"
        gz_path = tmp_dir / "dump.sql.gz"

        print(f"Running pg_dump → {gz_path.name} …")
        _run_pg_dump(db_url, sql_path)
        _assert_pg_dump_looks_valid(sql_path)
        _gzip_file(sql_path, gz_path)
        raw_mb = sql_path.stat().st_size / (1024 * 1024)
        gz_mb = gz_path.stat().st_size / (1024 * 1024)
        print(f"Dump size: {raw_mb:.2f} MB raw → {gz_mb:.2f} MB gzip")

        client = _s3_client()
        uploaded = _upload(client, bucket, key, gz_path)
        print(f"Uploaded s3://{bucket}/{key} ({uploaded / (1024 * 1024):.2f} MB)")

        latest_body = {
            "key": key,
            "uploaded_at": now.isoformat(),
            "bytes": uploaded,
            "retention_days": retention,
        }
        client.put_object(
            Bucket=bucket,
            Key=f"{prefix}latest.json",
            Body=json.dumps(latest_body, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )
        print(f"Wrote s3://{bucket}/{prefix}latest.json")

        removed = _prune_old_backups(client, bucket, prefix, retention)
        if removed:
            print(f"Pruned {removed} backup object(s) older than {retention} days.")


if __name__ == "__main__":
    main()
