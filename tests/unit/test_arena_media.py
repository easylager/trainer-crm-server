"""TASK-049: media license, hero pick, empty gallery contract."""
from __future__ import annotations

import pytest

from src.application.arena_media import (
    ARENA_MEDIA_MAX,
    ArenaMediaLimitError,
    InvalidMediaLicenseError,
    MEDIA_LICENSES,
    assert_can_add_arena_media,
    pick_hero_media,
    publicize_arena_media_payload,
    serialize_arena_media_payload,
    validate_media_license,
)
from src.application.photo_cdn import photo_url_from_cdn, public_photo_url


def test_license_own_does_not_need_source() -> None:
    assert validate_media_license("own") == "own"


def test_license_operator_requires_attribution_or_source() -> None:
    with pytest.raises(InvalidMediaLicenseError):
        validate_media_license("operator")
    assert validate_media_license("operator", source_url="https://arena.example") == "operator"
    assert validate_media_license("permitted", attribution="Каток Замок") == "permitted"


def test_unknown_license_rejected() -> None:
    with pytest.raises(InvalidMediaLicenseError):
        validate_media_license("google-images")
    assert "own" in MEDIA_LICENSES


def test_cdn_allows_trainers_and_arenas_not_legal() -> None:
    base = "https://cdn.example"
    assert photo_url_from_cdn("trainers/1/a.jpg", base) == "https://cdn.example/trainers/1/a.jpg"
    assert photo_url_from_cdn("arenas/9/b_card.jpg", base) == "https://cdn.example/arenas/9/b_card.jpg"
    assert photo_url_from_cdn("legal/secret.pdf", base) is None
    assert photo_url_from_cdn("trainers/1/a.jpg", "") is None


def test_hero_is_first_published_by_sort_order() -> None:
    rows = [
        {"id": 2, "sort_order": 1, "status": "published", "variants": {"hero": "arenas/1/b.jpg"}},
        {"id": 1, "sort_order": 0, "status": "published", "variants": {"hero": "arenas/1/a.jpg"}},
        {"id": 3, "sort_order": 0, "status": "pending", "variants": {"hero": "arenas/1/c.jpg"}},
    ]
    hero = pick_hero_media(rows)
    assert hero is not None
    assert hero["id"] == 1


def test_serialize_without_media_is_empty_not_missing() -> None:
    payload = serialize_arena_media_payload([])
    assert payload["hero"] is None
    assert payload["gallery"] == []


def test_seventh_photo_rejected() -> None:
    assert_can_add_arena_media(0)
    assert_can_add_arena_media(ARENA_MEDIA_MAX - 1)
    with pytest.raises(ArenaMediaLimitError):
        assert_can_add_arena_media(ARENA_MEDIA_MAX)


def test_publicize_maps_variant_keys_to_urls() -> None:
    payload = serialize_arena_media_payload(
        [
            {
                "id": 1,
                "sort_order": 0,
                "status": "published",
                "license": "own",
                "variants": {
                    "thumb": "arenas/3/a_thumb.jpg",
                    "card": "arenas/3/a_card.jpg",
                    "hero": "arenas/3/a_hero.jpg",
                },
            }
        ]
    )
    out = publicize_arena_media_payload(payload, cdn_base=None)
    assert out["hero"] is not None
    assert out["hero"]["variants"]["thumb"].endswith("/arenas/3/a_thumb.jpg")
    assert "storage_key" not in out["hero"]
    assert set(out["hero"]["variants"]) == {"thumb", "card", "hero"}


def test_public_photo_url_allows_arena_prefix() -> None:
    assert public_photo_url("arenas/1/x.jpg", cdn_base=None) == "/api/public/photos/arenas/1/x.jpg"
    assert public_photo_url("legal/secret.pdf", cdn_base=None) is None
