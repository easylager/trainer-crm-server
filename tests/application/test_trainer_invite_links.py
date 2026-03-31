"""trainer_invite_links: production URLs from env + profile ids."""

from src.application.trainer_invite_links import (
    build_trainer_invite_links,
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


def test_build_links_missing_city_or_service() -> None:
    for city, svc in ((None, 1), (1, None), (0, 1), (1, 0)):
        links, err = build_trainer_invite_links(
            webapp_base_url="https://x.com",
            client_bot_username="B",
            city_id=city,
            service_id=svc,
            trainer_id=1,
        )
        assert links is None
        assert err == "missing_city_or_service"
