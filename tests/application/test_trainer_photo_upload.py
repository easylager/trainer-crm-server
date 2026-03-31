"""upload_trainer_photo_from_bytes: size, image validation, storage errors (same path as API/bot)."""
from io import BytesIO

import pytest
from PIL import Image

from src.application.trainer_use_cases import (
    MAX_TRAINER_PHOTO_BYTES,
    create_trainer,
    upload_trainer_photo_from_bytes,
)


def _tiny_jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), color=(120, 40, 200)).save(buf, "JPEG", quality=80)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_upload_trainer_photo_too_large(db_session) -> None:
    tid = await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
    )
    body = b"x" * (MAX_TRAINER_PHOTO_BYTES + 1)
    ok, err, fk, fkl = await upload_trainer_photo_from_bytes(db_session, tid, body, "image/jpeg")
    assert (ok, err, fk, fkl) == (False, "too_large", None, None)


@pytest.mark.asyncio
async def test_upload_trainer_photo_not_image(db_session) -> None:
    tid = await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
    )
    ok, err, fk, fkl = await upload_trainer_photo_from_bytes(db_session, tid, b"not a jpeg", "image/jpeg")
    assert (ok, err, fk, fkl) == (False, "not_image", None, None)


@pytest.mark.asyncio
async def test_upload_trainer_photo_not_found_trainer(db_session, monkeypatch) -> None:
    await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
    )
    # trainers.id is int32 in DB; use an id that is not assigned to any row.
    ghost_id = min(999_000_777, 2_147_000_000)
    monkeypatch.setattr(
        "src.application.trainer_use_cases.s3.upload_photo",
        lambda tid, _body, _ct: (f"trainers/{tid}/fake.jpg", None),
    )
    ok, err, fk, fkl = await upload_trainer_photo_from_bytes(db_session, ghost_id, _tiny_jpeg(), "image/jpeg")
    assert ok is False
    assert err == "not_found"
    assert fk is None


@pytest.mark.asyncio
async def test_upload_trainer_photo_storage_error(db_session, monkeypatch) -> None:
    tid = await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
    )

    def boom(*_a, **_k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr("src.application.trainer_use_cases.s3.upload_photo", boom)
    ok, err, fk, fkl = await upload_trainer_photo_from_bytes(db_session, tid, _tiny_jpeg(), "image/jpeg")
    assert (ok, err, fk, fkl) == (False, "storage", None, None)


@pytest.mark.asyncio
async def test_upload_trainer_photo_success(db_session, monkeypatch) -> None:
    tid = await create_trainer(
        db_session,
        profile={"first_name": "A", "last_name": "B", "age": 30},
    )
    monkeypatch.setattr(
        "src.application.trainer_use_cases.s3.upload_photo",
        lambda tid, body, ct: (
            f"trainers/{tid}/abc.jpg",
            f"trainers/{tid}/abc_list.jpg",
        ),
    )
    ok, err, fk, fkl = await upload_trainer_photo_from_bytes(db_session, tid, _tiny_jpeg(), "image/jpeg")
    assert ok and err == ""
    assert fk == f"trainers/{tid}/abc.jpg"
    assert fkl == f"trainers/{tid}/abc_list.jpg"

    from sqlalchemy import text

    r = await db_session.execute(
        text("SELECT file_key, file_key_list FROM trainer_photos WHERE trainer_id = :tid"),
        {"tid": tid},
    )
    rows = r.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == f"trainers/{tid}/abc.jpg"
    assert rows[0][1] == f"trainers/{tid}/abc_list.jpg"
