from src.shared.public_trainer_payload import (
    PUBLIC_CATALOG_TRAINER_DROP_KEYS,
    sanitize_trainer_for_public_catalog,
)


def test_sanitize_drops_internal_fields() -> None:
    t = {
        "id": 1,
        "telegram_id": 12345,
        "status": "active",
        "moderation_feedback": "secret",
        "moderation_submitted_at": "2020-01-01",
        "created_at": "2019-01-01",
        "profile_pending": {},
        "photo_pending": {},
        "is_catalog_visible": False,
        "profile": {"first_name": "A"},
    }
    out = sanitize_trainer_for_public_catalog(t)
    assert not (PUBLIC_CATALOG_TRAINER_DROP_KEYS & set(out.keys()))
    assert out["id"] == 1
    assert "telegram_id" not in out
    assert "moderation_feedback" not in out
    assert "moderation_submitted_at" not in out
    assert "created_at" not in out
    assert out["profile"] == {"first_name": "A"}
