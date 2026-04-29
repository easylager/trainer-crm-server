"""Share message composer: human-first copy, deep link embedded in text."""

from src.application.client_share_message import (
    CLIENT_SHARE_CONTEXT_CATALOG,
    CLIENT_SHARE_CONTEXT_MY_TRAINER,
    compose_client_share_message,
    share_body_for_native_share_dialog,
)


def test_compose_share_message_structure_and_link() -> None:
    dl = "https://t.me/ExBot?start=share_ref_42"
    text = compose_client_share_message(
        share_context=CLIENT_SHARE_CONTEXT_MY_TRAINER,
        trainer_display_name="Илья Ковалёв",
        service_names=["Хоккей", "Skating skills"],
        city_name="Минск",
        primary_arena_name="ТЦ Замок",
        deep_link=dl,
    )
    assert text.startswith(dl + "\n")
    assert "Илья Ковалёв" in text
    assert "Хоккей" in text
    assert "Минск" in text and "ТЦ Замок" in text
    assert "Вот тренер, к которому я хожу" in text


def test_share_body_for_native_share_dialog_strips_leading_link() -> None:
    dl = "https://t.me/ExBot?start=share_ref_42"
    full = compose_client_share_message(
        share_context=CLIENT_SHARE_CONTEXT_MY_TRAINER,
        trainer_display_name="Илья Ковалёв",
        service_names=["Хоккей"],
        city_name="Минск",
        primary_arena_name="ТЦ Замок",
        deep_link=dl,
    )
    body = share_body_for_native_share_dialog(full, dl)
    assert dl not in body
    assert body.startswith("Вот тренер, к которому я хожу")


def test_share_body_legacy_message_link_last_line_still_splits() -> None:
    """Older cached clients may still send full message with URL last — tolerate for native url=/text=."""
    dl = "https://t.me/x?start=y"
    legacy_full = (
        "Вот тренер, к которому я хожу — могу порекомендовать 👇\n\nИлья\n\n"
        "Профиль, свободные слоты и запись:\n"
        + dl
    )
    body = share_body_for_native_share_dialog(legacy_full, dl)
    assert dl not in body


def test_share_copy_same_regardless_of_context() -> None:
    """Entry point (hub vs catalog vs booking) does not change the message body."""
    dl = "https://t.me/b?start=x"
    kw = dict(
        trainer_display_name="Анна",
        service_names=["ОФП"],
        city_name=None,
        primary_arena_name=None,
        deep_link=dl,
    )
    t_my = compose_client_share_message(share_context=CLIENT_SHARE_CONTEXT_MY_TRAINER, **kw)
    t_cat = compose_client_share_message(share_context=CLIENT_SHARE_CONTEXT_CATALOG, **kw)
    assert t_my == t_cat
