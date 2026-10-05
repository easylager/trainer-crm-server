"""TASK-146: адреса публичной страницы места и диплинки в Telegram."""

from __future__ import annotations

from src.application.place_links import (
    catalog_start_param,
    is_valid_start_param,
    parse_catalog_start_param,
    parse_place_deep_link,
    parse_place_start_param,
    place_image_url,
    place_page_url,
    place_start_param,
    public_telegram_cta_url,
    telegram_open_link,
)


def test_place_url_is_city_scoped_and_readable() -> None:
    url = place_page_url(base_url="https://glide.by/", city_name="Минск", slug="minsk-arena")
    assert url == "https://glide.by/p/minsk/minsk-arena"
    assert place_page_url(
        base_url="https://glide.by", city_name="Минск", slug="minsk-arena", session_id=5, invite=True
    ).endswith("/p/minsk/minsk-arena?s=5&i=1")
    assert (
        place_image_url(base_url="https://glide.by", city_name="Брест", slug="x", story=True)
        == "https://glide.by/p/brest/x/story.png"
    )
    assert (
        place_image_url(
            base_url="https://glide.by",
            city_name="Минск",
            slug="zamok",
            session_id=42,
            invite=True,
            story=True,
        )
        == "https://glide.by/p/minsk/zamok/session/42/story.png?i=1"
    )


def test_start_params_fit_telegram_limits() -> None:
    for value in (
        place_start_param(123456789),
        place_start_param(123456789, 987654321),
        catalog_start_param(12, "coach"),
        catalog_start_param(9),
        catalog_start_param(12, "skate", "today_evening"),
        catalog_start_param(12, "outdoor", "weekend"),
    ):
        assert is_valid_start_param(value)
    assert catalog_start_param(12, "sauna") == "catalog_12"
    assert catalog_start_param(12, "shop", "weekend") == "catalog_12_shop", "у магазина окна нет"


def test_start_params_round_trip() -> None:
    assert parse_place_start_param("arena_42") == 42
    assert parse_place_start_param("arena_42_s_7") == 42
    assert parse_place_deep_link("arena_42_s_7") == (42, 7)
    assert parse_place_deep_link("arena_42") == (42, None)
    assert parse_place_start_param("arena_minsk-arena") is None, "slug неоднозначен между городами"
    assert parse_catalog_start_param("catalog_12_shop") == (12, "shop", None)
    assert parse_catalog_start_param("catalog_12") == (12, None, None)
    assert parse_catalog_start_param("catalog_12_sauna") == (12, None, None)
    assert parse_catalog_start_param("catalog_12_skate_weekend") == (12, "skate", "weekend")
    assert parse_catalog_start_param("catalog_12_skate_today_evening") == (12, "skate", "today_evening")
    assert parse_catalog_start_param("catalog_12_outdoor_tomorrow") == (12, "outdoor", "tomorrow")
    assert parse_catalog_start_param("catalog_x") is None
    assert parse_catalog_start_param("catalog") == (None, None, None), "маркетинговый вход /go"
    assert parse_catalog_start_param("cert_ABC") is None


def test_open_link_prefers_startapp_and_falls_back_to_bot() -> None:
    assert (
        telegram_open_link(client_bot_username="@glide_bot", mini_app_short_name="app", start_param="arena_1")
        == "https://t.me/glide_bot/app?startapp=arena_1"
    )
    assert (
        telegram_open_link(client_bot_username="glide_bot", mini_app_short_name=None, start_param="arena_1")
        == "https://t.me/glide_bot?start=arena_1"
    )
    assert (
        telegram_open_link(
            client_bot_username="glide_bot", mini_app_short_name=None, start_param="arena_1", main_mini_app=True
        )
        == "https://t.me/glide_bot?startapp=arena_1"
    )
    assert telegram_open_link(client_bot_username=None, mini_app_short_name="app", start_param="arena_1") is None
    assert telegram_open_link(client_bot_username="b", mini_app_short_name=None, start_param="bad param") is None


def test_public_telegram_cta_proxy_url() -> None:
    url = public_telegram_cta_url(
        "https://glide.by",
        start_param="arena_9",
        surface="place_page",
        city_id=1,
        arena_id=9,
    )
    assert url is not None
    assert url.startswith("https://glide.by/api/public/catalog/open-telegram?")
    assert "startapp=arena_9" in url
    assert "surface=place_page" in url
