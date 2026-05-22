"""trainer_invite_links: production URLs from env + profile ids."""

from src.application.trainer_invite_links import (
    build_trainer_invite_links,
    build_trainer_universal_invite_link,
    build_client_start_payload,
    normalize_client_bot_username,
)


def test_normalize_client_bot_username_strips_at() -> None:
    assert normalize_client_bot_username("@MyBot") == "MyBot"
    assert normalize_client_bot_username("MyBot") == "MyBot"
    assert normalize_client_bot_username("  x  ") == "x"


def test_build_client_start_payload_matches_client_bot() -> None:
    assert build_client_start_payload(1, 2, 3) == "client_1_2_3"


def test_build_links_https_catalog_and_tme() -> None:
    links, err = build_trainer_invite_links(
        webapp_base_url="https://api.example.com/",
        client_bot_username="ClientBot",
        city_id=5,
        service_id=7,
        trainer_id=11,
    )
    assert err is None
    assert links is not None
    assert links.client_bot_deep_link == "https://t.me/ClientBot?start=client_5_7_11"
    assert links.catalog_page_url == "https://api.example.com/webapp/catalog"


def test_build_links_no_catalog_without_https() -> None:
    links, err = build_trainer_invite_links(
        webapp_base_url="http://localhost:8000",
        client_bot_username="ClientBot",
        city_id=1,
        service_id=2,
        trainer_id=3,
    )
    assert err is None
    assert links is not None
    assert links.catalog_page_url is None


def test_build_links_missing_username() -> None:
    links, err = build_trainer_invite_links(
        webapp_base_url="https://x.com",
        client_bot_username=None,
        city_id=1,
        service_id=2,
        trainer_id=3,
    )
    assert links is None
    assert err == "missing_username"


def test_build_links_missing_city_or_invalid_trainer() -> None:
    """City and trainer_id must be positive; service is optional (encoded as 0 in /start payload)."""
    for city, tid in ((None, 1), (0, 1), (1, 0)):
        links, err = build_trainer_invite_links(
            webapp_base_url="https://x.com",
            client_bot_username="B",
            city_id=city,
            service_id=1,
            trainer_id=tid,
        )
        assert links is None
        assert err == "missing_city_or_service"


def test_build_links_service_optional_zero_in_payload() -> None:
    """Missing or zero service_id still builds a deep link with service segment 0."""
    for svc in (None, 0):
        links, err = build_trainer_invite_links(
            webapp_base_url="https://x.com",
            client_bot_username="B",
            city_id=1,
            service_id=svc,
            trainer_id=1,
        )
        assert err is None
        assert links is not None
        assert links.client_bot_deep_link == "https://t.me/B?start=client_1_0_1"
        assert links.catalog_page_url == "https://x.com/webapp/catalog"


def test_build_universal_invite_link_matches_hub_paperclip() -> None:
    link, err = build_trainer_universal_invite_link(
        client_bot_username="@ClientBot",
        trainer_id=9,
    )
    assert err is None
    assert link == "https://t.me/ClientBot?start=welcome_ref_9"


def test_build_universal_invite_link_missing_username() -> None:
    link, err = build_trainer_universal_invite_link(
        client_bot_username=None,
        trainer_id=9,
    )
    assert link is None
    assert err == "missing_username"
