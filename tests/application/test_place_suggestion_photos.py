import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import text

from src.application import place_suggestion_photos as photos
from src.application import place_suggestion_use_cases as uc


async def _noop():
    return None


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Без Telegram (в .env боевой токен) и без S3: фото пишутся в tmp."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", lambda sid: _noop())
    monkeypatch.setattr(uc, "notify_author_approved", lambda sid: _noop())
    monkeypatch.setattr("src.infrastructure.s3._use_local", lambda: True)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (20, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


async def _city(db_session) -> int:
    r = await db_session.execute(text(
        "INSERT INTO cities (name, sort_order, is_active, country) VALUES ('Фотоград-psp', 1, true, 'BY') RETURNING id"
    ))
    await db_session.commit()
    return int(r.scalar_one())


async def _suggestion(db_session) -> dict:
    return await uc.create_place_suggestion(
        db_session, source="site", kind="ice", city_id=await _city(db_session), new_city=None,
        name="Каток с фото", address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
    )


@pytest.mark.asyncio
async def test_create_returns_upload_token_and_photo_is_stored(db_session):
    res = await _suggestion(db_session)
    assert res["upload_token"]
    out = await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], _jpeg(), "image/jpeg")
    listed = await photos.list_suggestion_photos(db_session, res["id"])
    assert [p["id"] for p in listed] == [out["id"]] and listed[0]["publish"] is True
    assert listed[0]["url"].startswith("/api/webapp/admin/place-suggestions/")
    body, _ = await photos.get_photo_bytes(db_session, res["id"], out["id"])
    assert body[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_wrong_or_stale_token_and_limit(db_session):
    res = await _suggestion(db_session)
    with pytest.raises(photos.SuggestionPhotoError, match="forbidden"):
        await photos.add_suggestion_photo(db_session, res["id"], "nope", _jpeg(), "image/jpeg")
    late = datetime.now(timezone.utc) + photos.PHOTO_TOKEN_TTL + timedelta(minutes=1)
    with pytest.raises(photos.SuggestionPhotoError, match="forbidden"):
        await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], _jpeg(), "image/jpeg", now=late)
    with pytest.raises(photos.SuggestionPhotoError, match="not_image"):
        await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], b"not an image", "image/jpeg")
    for _ in range(photos.MAX_PHOTOS):
        await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], _jpeg(), "image/jpeg")
    with pytest.raises(photos.SuggestionPhotoError, match="limit"):
        await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], _jpeg(), "image/jpeg")


@pytest.mark.asyncio
async def test_approve_copies_published_photos_and_closes_token(db_session):
    res = await _suggestion(db_session)
    keep = await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], _jpeg(), "image/jpeg")
    skip = await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], _jpeg(), "image/jpeg")
    assert await photos.set_photo_publish(db_session, res["id"], skip["id"], False)
    out = await uc.approve_place_suggestion(db_session, res["id"], admin_id=1)
    assert out["photos_copied"] == 1
    media = (await db_session.execute(text(
        "SELECT license, attribution FROM media WHERE owner_type = 'arena' AND owner_id = :a"), {"a": out["arena_id"]})).all()
    assert [(m.license, m.attribution) for m in media] == [("user", photos.VISITOR_ATTRIBUTION)]
    token = (await db_session.execute(text(
        "SELECT photo_token FROM place_suggestions WHERE id = :id"), {"id": res["id"]})).scalar_one()
    assert token is None
    with pytest.raises(photos.SuggestionPhotoError, match="forbidden"):
        await photos.add_suggestion_photo(db_session, res["id"], res["upload_token"], _jpeg(), "image/jpeg")
    del keep
