"""trainer_invite_links: production URLs from env + profile ids."""

from src.application.trainer_invite_links import (
    build_trainer_invite_links,
    build_trainer_preview_link,
    build_trainer_preview_payload,
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


def test_build_links_returns_tme_deep_link() -> None:
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


def test_build_links_never_returns_catalog_page_url() -> None:
    """/webapp/catalog only authenticates inside a Telegram Mini App launch (initData) — a bare
    link handed out as shareable text can't carry that context, so it must never be built."""
    links, err = build_trainer_invite_links(
        webapp_base_url="https://api.example.com/",
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
        assert links.catalog_page_url is None


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


def test_build_trainer_preview_payload_matches_client_bot() -> None:
    assert build_trainer_preview_payload(42) == "preview_42"


def test_build_trainer_preview_link_returns_tme_deep_link() -> None:
    link, err = build_trainer_preview_link(client_bot_username="@ClientBot", trainer_id=42)
    assert err is None
    assert link == "https://t.me/ClientBot?start=preview_42"


def test_build_trainer_preview_link_missing_username() -> None:
    link, err = build_trainer_preview_link(client_bot_username=None, trainer_id=42)
    assert link is None
    assert err == "missing_username"


def test_build_trainer_preview_link_invalid_trainer_id() -> None:
    link, err = build_trainer_preview_link(client_bot_username="B", trainer_id=0)
    assert link is None
    assert err == "invalid_trainer_id"


def test_ref_payloads_carry_optional_slot_and_old_format_is_unchanged() -> None:
    from src.application.trainer_invite_links import (
        build_share_ref_payload,
        build_trainer_share_link,
        build_welcome_ref_payload,
        parse_ref_slot,
    )

    assert build_welcome_ref_payload(9) == "welcome_ref_9"
    assert build_share_ref_payload(9) == "share_ref_9"
    assert build_welcome_ref_payload(9, 55) == "welcome_ref_9_s_55"
    assert build_share_ref_payload(9, 55) == "share_ref_9_s_55"
    link, _ = build_trainer_universal_invite_link(client_bot_username="B", trainer_id=9, slot_id=55)
    assert link == "https://t.me/B?start=welcome_ref_9_s_55"
    rec, _ = build_trainer_share_link(webapp_base_url="https://x", client_bot_username="B", trainer_id=9, slot_id=55)
    assert rec is not None and rec.bot_deep_link == "https://t.me/B?start=share_ref_9_s_55"
    # start_param у Telegram — до 64 символов: самые длинные id укладываются.
    assert len(build_welcome_ref_payload(999_999_999, 9_999_999_999)) <= 64
    assert parse_ref_slot("welcome_ref_9_s_55", "welcome_ref_") == (9, 55)
    assert parse_ref_slot("welcome_ref_9", "welcome_ref_") is None
    assert parse_ref_slot("welcome_ref_9_s_0", "welcome_ref_") is None
