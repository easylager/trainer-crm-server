"""TASK-146: адреса публичной страницы места и диплинки в Telegram."""

from __future__ import annotations

from src.application.place_links import (
    SHARE_SRC_VALUES,
    catalog_start_param,
    clean_share_src,
    is_valid_start_param,
    parse_catalog_start_param,
    parse_place_deep_link,
    parse_place_start_param,
    place_image_url,
    place_page_url,
    place_start_param,
    public_telegram_cta_url,
    parse_trainer_deep_link,
    telegram_open_link,
    trainer_start_param,
    trainer_webapp_url,
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


def test_trainer_start_param_roundtrip() -> None:
    assert trainer_start_param(42) == "trainer_42"
    assert trainer_start_param(7, 3) == "trainer_7_a_3"
    assert is_valid_start_param("trainer_42")
    assert parse_trainer_deep_link("trainer_42") == (42, None)
    assert parse_trainer_deep_link("trainer_7_a_3") == (7, 3)
    assert parse_trainer_deep_link("arena_1") is None


def test_trainer_start_param_intent_tail_for_site_buttons() -> None:
    """Кнопки сайта «Сохранить» / «Оставить заявку»: хвост ``_i_save`` / ``_i_request``; чужое значение отбрасывается."""
    from src.application.place_links import parse_trainer_start_param

    assert trainer_start_param(7, via="k1", intent="save") == "trainer_7_v_k1_i_save"
    assert trainer_start_param(7, intent="request") == "trainer_7_i_request"
    assert trainer_start_param(7, intent="drop") == "trainer_7"
    # Ссылки кнопок сайта без каткa и слота — самый длинный реальный вариант влезает в 64 символа Telegram.
    assert is_valid_start_param(trainer_start_param(2_000_000_000, via="k999999999", intent="request"))
    assert parse_trainer_start_param("trainer_7_i_save")["intent"] == "save"
    assert parse_trainer_start_param("trainer_7_v_p3_i_REQUEST")["intent"] == "request"
    assert parse_trainer_start_param("trainer_7_i_delete")["intent"] is None
    assert parse_trainer_start_param("trainer_7_i_save_i_request")["intent"] == "save"


def test_trainer_start_param_slot_and_via_tails_any_order() -> None:
    """TASK-357: ``_s_<slot>`` — запись на время; TASK-351 добавляет ``_v_<via>``; порядок хвостов любой."""
    from src.application.place_links import parse_trainer_start_param

    assert trainer_start_param(7, slot_id=55) == "trainer_7_s_55"
    assert trainer_start_param(7, 3, 55) == "trainer_7_a_3_s_55"
    assert is_valid_start_param(trainer_start_param(2_000_000_000, 2_000_000_000, 2_000_000_000))
    want = {"trainer_id": 7, "arena_id": 3, "slot_id": 55, "via": "p3", "intent": None}
    assert parse_trainer_start_param("trainer_7_a_3_s_55_v_p3") == want
    assert parse_trainer_start_param("trainer_7_v_p3_s_55_a_3") == want
    assert parse_trainer_start_param("trainer_7_s_55_x_zz") == {
        "trainer_id": 7,
        "arena_id": None,
        "slot_id": 55,
        "via": None,
        "intent": None,
    }
    assert parse_trainer_start_param("trainer_7_s_0")["slot_id"] is None
    assert parse_trainer_start_param("trainer_7_a_") is None
    assert parse_trainer_deep_link("trainer_7_s_55_a_3") == (7, 3)


def test_start_params_fit_telegram_limits() -> None:
    for value in (
        place_start_param(123456789),
        place_start_param(123456789, 987654321),
        trainer_start_param(99),
        catalog_start_param(12, "coach"),
        catalog_start_param(9),
        catalog_start_param(12, "skate", "today_evening"),
        catalog_start_param(12, "outdoor", "weekend"),
    ):
        assert is_valid_start_param(value)
    assert catalog_start_param(12, "sauna") == "catalog_12"
    assert catalog_start_param(12, "shop", "weekend") == "catalog_12_shop", "у магазина окна нет"
    assert catalog_start_param(12, "ohm", "weekend") == "catalog_12_ohm_weekend"
    assert catalog_start_param(12, "service", "weekend") == "catalog_12_service", "у услуг окна нет"


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
    assert parse_catalog_start_param("catalog_12_ohm") == (12, "ohm", None)
    assert parse_catalog_start_param("catalog_12_ohm_weekend") == (12, "ohm", "weekend")
    assert parse_catalog_start_param("catalog_12_service") == (12, "service", None)
    assert parse_catalog_start_param("catalog_x") is None
    assert parse_catalog_start_param("catalog") == (None, None, None), "маркетинговый вход /go"
    assert parse_catalog_start_param("cert_ABC") is None


def test_selection_start_param_ohm_and_service() -> None:
    from src.application.selection_page import selection_start_param

    assert selection_start_param(city_id=12, venue=None, when=None, kind="ohm") == "catalog_12_ohm"
    assert (
        selection_start_param(city_id=12, venue=None, when="weekend", kind="ohm") == "catalog_12_ohm_weekend"
    )
    for svc in ("sharpening", "rental", "service"):
        assert selection_start_param(city_id=12, venue="ice", when="weekend", svc=svc) == "catalog_12_service"
    assert selection_start_param(city_id=12, venue="service", when="today") == "catalog_12_service"
    assert selection_start_param(city_id=12, venue="shop", when="weekend") == "catalog_12_shop"
    assert selection_start_param(city_id=12, venue="gym", when=None) == "catalog_12_gym"


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


def test_clean_share_src_and_place_query() -> None:
    assert clean_share_src("TG") == "tg"
    assert clean_share_src("evil") is None
    assert clean_share_src("<script>") is None
    assert set(SHARE_SRC_VALUES) == {"tg", "vb", "wa", "vk", "copy", "story", "sys", "img"}
    url = place_page_url(
        base_url="https://glide.by",
        city_name="Минск",
        slug="minsk-arena",
        session_id=5,
        src="wa",
    )
    assert url.endswith("?s=5&src=wa")
    assert place_image_url(
        base_url="https://glide.by",
        city_name="Минск",
        slug="minsk-arena",
        session_id=5,
    ).endswith("/session/5/og.png")
    assert "src=" not in place_image_url(
        base_url="https://glide.by",
        city_name="Минск",
        slug="minsk-arena",
        session_id=5,
    )


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
    with_src = public_telegram_cta_url(
        "https://glide.by",
        start_param="arena_9",
        surface="place_page",
        share_src="copy",
        session_id=42,
    )
    assert with_src is not None
    assert "src=copy" in with_src and "s=42" in with_src


def test_trainer_webapp_url_flag_off_keeps_each_old_address(monkeypatch) -> None:
    monkeypatch.delenv("UNIFIED_TRAINER_CARD_ENABLED", raising=False)
    base = "https://glide.example"
    assert trainer_webapp_url(base, 7, city_id=2, service_id=3, arena_id=4, via="share", legacy="catalog") == (
        f"{base}/webapp/catalog?trainer_id=7&city_id=2&service_id=3&arena_id=4&via=share"
    )
    assert trainer_webapp_url(base, 7, legacy="book") == (
        f"{base}/webapp/book?trainer_id=7&v=20260420d&force_service_choice=1"
    )
    assert trainer_webapp_url(base, 7, service_id=3, legacy="book") == (
        f"{base}/webapp/book?trainer_id=7&v=20260420d&service_id=3"
    )
    assert trainer_webapp_url(base, 7, legacy="book_session") == f"{base}/webapp/book?trainer_id=7"
    assert trainer_webapp_url(base, 7, service_id=3, legacy="book_session") == (
        f"{base}/webapp/book?trainer_id=7&service_id=3"
    )
    assert trainer_webapp_url(base, 7, slot_id=55, legacy="book_plain") == (
        f"{base}/webapp/book?trainer_id=7&slot_id=55"
    )
    assert trainer_webapp_url(base, 7, legacy="book_plain") == f"{base}/webapp/book?trainer_id=7"
    assert trainer_webapp_url(base, 7, slot_id=55, via="link", legacy="slot") == (
        f"{base}/webapp/trainers?trainer_id=7&slot_id=55&via=link"
    )


def test_trainer_webapp_url_flag_on_is_the_start_param_projection(monkeypatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    param = trainer_start_param(7, 3, 55, via="p3", intent="save")
    assert param == "trainer_7_a_3_s_55_v_p3_i_save"
    url = trainer_webapp_url(
        "https://glide.example",
        7,
        arena_id=3,
        slot_id=55,
        via="p3",
        intent="save",
        service_id=9,
        city_id=2,
        legacy="book",
    )
    assert url == (
        "https://glide.example/webapp/trainers?"
        "trainer_id=7&slot_id=55&arena_id=3&via=p3&intent=save&service_id=9&city_id=2"
    )
    # via=link не входит в контракт _v_ и не должен теряться в startapp-редиректе.
    linked = trainer_webapp_url("https://glide.example", 7, via="link", legacy="catalog")
    assert linked == "https://glide.example/webapp/trainers?trainer_id=7&via=link"
    assert "startapp=" not in linked
