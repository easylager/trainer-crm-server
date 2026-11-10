"""Публичные входы в Telegram через /start (флаг PUBLIC_ENTRY_VIA_START) и универсальный ответ бота."""

from __future__ import annotations

import inspect
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramForbiddenError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.place_links import (
    is_valid_start_param,
    public_telegram_entry_link,
    trainer_start_param,
)
from src.bot import messages as msg
from src.bot import start_entry
from src.bot.handlers import client_handlers
from src.bot.start_entry import start_entry_reply

BOT = "glide_test_bot"
BASE = "https://glide.test"

#: По одному параметру на тип публичного входа.
PUBLIC_PARAMS = {
    "place": "arena_42_s_9",
    "trainer_slot": "trainer_7_s_55_v_p3",
    "trainer_intent": "trainer_7_i_request",
    "catalog": "catalog_12_skate_weekend",
    "catalog_any": "catalog",
    "follow_bell": "follow_arena_3",
    "company": "company_9",
    "match": "kkm_5",
    "game_promo": "kks_insta",
}


def _settings(*, via_start: bool, main: bool = True, short: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        client_bot_username=BOT,
        client_mini_app_short_name=short,
        client_bot_main_mini_app=main,
        public_entry_via_start=via_start,
    )


# ---------- хелпер ----------


@pytest.mark.parametrize("param", list(PUBLIC_PARAMS.values()))
def test_helper_off_is_exactly_the_old_link(param: str) -> None:
    assert public_telegram_entry_link(_settings(via_start=False), start_param=param) == (
        f"https://t.me/{BOT}?startapp={param}"
    )
    assert public_telegram_entry_link(_settings(via_start=False, short="app"), start_param=param) == (
        f"https://t.me/{BOT}/app?startapp={param}"
    )
    assert public_telegram_entry_link(_settings(via_start=False, main=False), start_param=param) == (
        f"https://t.me/{BOT}?start={param}"
    )


@pytest.mark.parametrize("param", list(PUBLIC_PARAMS.values()))
def test_helper_on_always_goes_through_start(param: str) -> None:
    for settings in (_settings(via_start=True), _settings(via_start=True, short="app")):
        assert public_telegram_entry_link(settings, start_param=param) == f"https://t.me/{BOT}?start={param}"


def test_helper_rejects_bad_params_and_missing_bot_in_both_modes() -> None:
    for flag in (False, True):
        assert public_telegram_entry_link(_settings(via_start=flag), start_param="bad param") is None
        assert public_telegram_entry_link(_settings(via_start=flag), start_param="x" * 65) is None
        no_bot = _settings(via_start=flag)
        no_bot.client_bot_username = None
        assert public_telegram_entry_link(no_bot, start_param="arena_1") is None


def test_longest_trainer_param_fits_and_survives() -> None:
    longest = trainer_start_param(999_999_999, arena_id=999_999_999, slot_id=999_999_999, via="p999999999", intent="request")
    assert len(longest) <= 64 and is_valid_start_param(longest)
    assert public_telegram_entry_link(_settings(via_start=True), start_param=longest).endswith(f"?start={longest}")
    reply = start_entry_reply(longest, webapp_base_url=BASE)
    assert reply["url"] == f"{BASE}/webapp/client-home?startapp={longest}"


def test_default_setting_is_off() -> None:
    from src.shared.config import Settings

    assert Settings.model_fields["public_entry_via_start"].default is False


# ---------- горловина /open-telegram ----------


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


@pytest.fixture
def bot_env(monkeypatch):
    monkeypatch.setenv("CLIENT_BOT_USERNAME", BOT)
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)
    monkeypatch.setenv("WEBAPP_BASE_URL", BASE)
    monkeypatch.delenv("PUBLIC_ENTRY_VIA_START", raising=False)
    return monkeypatch


async def _cta_count(db_session, start_param: str) -> int:
    return int(
        (
            await db_session.execute(
                text("SELECT COUNT(*) FROM catalog_consumer_events WHERE kind = 'public_telegram_cta' AND start_param = :p"),
                {"p": start_param},
            )
        ).scalar_one()
    )


_GATE_PARAMS = {**PUBLIC_PARAMS, "rink_bell": "watch_3", "match_bell": "mbell_4"}


@pytest.mark.asyncio
@pytest.mark.parametrize("via_start", [False, True])
async def test_open_telegram_redirect_and_count_for_every_param(app_use_test_db, db_session, bot_env, via_start) -> None:
    if via_start:
        bot_env.setenv("PUBLIC_ENTRY_VIA_START", "true")
    for kind, param in _GATE_PARAMS.items():
        before = await _cta_count(db_session, param)
        async with _client() as client:
            resp = await client.get(
                "/api/public/catalog/open-telegram",
                params={"startapp": param, "surface": "place_page"},
                follow_redirects=False,
            )
        assert resp.status_code == 302, kind
        bell = kind in ("rink_bell", "match_bell")
        expected = f"https://t.me/{BOT}?start={param}" if (via_start or bell) else f"https://t.me/{BOT}?startapp={param}"
        assert resp.headers["location"] == expected, kind
        assert await _cta_count(db_session, param) == before + 1, kind


# ---------- /kk ----------


@pytest.mark.asyncio
@pytest.mark.parametrize("via_start", [False, True])
async def test_kk_promo_page_button_and_mobile_hop(bot_env, via_start) -> None:
    if via_start:
        bot_env.setenv("PUBLIC_ENTRY_VIA_START", "1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = (await client.get("/kk", params={"s": "insta"}, headers={"user-agent": "Mozilla/5.0 (iPhone)"})).text
    go = f"https://t.me/{BOT}?start=kks_insta" if via_start else f"https://t.me/{BOT}?startapp=kks_insta"
    assert f'href="{go}"' in page
    assert f'location.replace("{go}")' in page


# ---------- /go ----------


@pytest.mark.asyncio
@pytest.mark.parametrize("via_start", [False, True])
async def test_go_marketing_link(app_use_test_db, bot_env, via_start) -> None:
    if via_start:
        bot_env.setenv("PUBLIC_ENTRY_VIA_START", "1")
    async with _client() as client:
        resp = await client.get("/go", follow_redirects=False)
    assert resp.status_code == 302
    expected = f"https://t.me/{BOT}?start=catalog" if via_start else f"https://t.me/{BOT}?startapp=catalog"
    assert resp.headers["location"] == expected


# ---------- открытка «Зови» (превью матча — в tests/api/test_hockey_match_share.py) ----------


def test_zovi_exit_link_follows_the_flag(bot_env) -> None:
    from src.api.routes.zovi_pages import _exit_url

    invite = {"match": {"start_param": "kkm_5"}}
    assert _exit_url(invite, BASE) == f"https://t.me/{BOT}?startapp=kkm_5"
    bot_env.setenv("PUBLIC_ENTRY_VIA_START", "1")
    assert _exit_url(invite, BASE) == f"https://t.me/{BOT}?start=kkm_5"
    assert _exit_url({}, BASE) == f"{BASE}/"


# ---------- ответ бота: чистая часть ----------


@pytest.mark.parametrize(
    "param, path",
    [
        ("trainer_7_s_55_v_p3", "client-home"),
        ("trainer_7_i_save", "client-home"),
        ("follow_arena_3", "client-home"),
        ("company_9", "client-home"),
        ("kkm_5_k3x9abcd", "client-home"),
        ("kkn_42_h", "client-home"),
        ("kkmo_7", "client-home"),
        ("kkoff", "client-home"),
        ("kks_insta", "kto-kogo"),
        ("kk_AB12", "kto-kogo"),
        ("kkl_AB12", "kto-kogo"),
        ("kkr", "kto-kogo"),
        ("something-new_1", "client-home"),
    ],
)
def test_reply_button_opens_the_same_screen(param: str, path: str) -> None:
    reply = start_entry_reply(param, webapp_base_url=BASE + "/")
    assert reply is not None
    assert reply["url"] == f"{BASE}/webapp/{path}?startapp={param}"
    game = param.startswith("kk") and not param.startswith("kkm_")
    assert reply["text"] == (msg.CLIENT_START_ENTRY_GAME if game else msg.CLIENT_START_ENTRY_APP)
    assert reply["button_text"] == (msg.CLIENT_BUTTON_START_ENTRY_GAME if game else msg.CLIENT_BUTTON_START_ENTRY_APP)


@pytest.mark.parametrize("payload", ["", "   ", "bad param", "привет", "x" * 65, "a/b", None])
def test_reply_none_for_invalid_payload(payload) -> None:
    assert start_entry_reply(payload, webapp_base_url=BASE) is None


@pytest.mark.parametrize("base", ["", None, "http://localhost:8000", "glide.test"])
def test_reply_none_without_https(base) -> None:
    assert start_entry_reply("trainer_7", webapp_base_url=base) is None


@pytest.mark.parametrize(
    "payload",
    [
        "welcome_t_x",
        "welcome_ref_7",
        "share_ref_7",
        "preview_7",
        "pass_1_ref_2",
        "client_1_0_2",
        "cert_ABC",
        "col_studio",
        "sg_tok",
        "mbell_4_x",
        "watch_x",
        "wbell_1",
        "wphoto_1",
        "wgone_1",
        "wnear",
    ],
)
def test_bot_only_params_keep_the_old_welcome(payload) -> None:
    """Ветка бота не ответила (кривая ссылка, нет коллектива…) — прежнее приветствие, не кнопка в Mini App."""
    assert start_entry_reply(payload, webapp_base_url=BASE) is None


_EMOJI_RE = re.compile("[\U0001f300-\U0001faff☀-➿⭐✅]")


def test_texts_are_clean() -> None:
    texts = [
        msg.CLIENT_START_ENTRY_GAME,
        msg.CLIENT_BUTTON_START_ENTRY_GAME,
        msg.CLIENT_START_ENTRY_APP,
        msg.CLIENT_BUTTON_START_ENTRY_APP,
    ]
    for value in texts:
        assert value.strip()
        assert not _EMOJI_RE.search(value), value
        low = value.lower()
        for word in ("ставк", "срок", "источник", "start", "mini app", "параметр", "ссылк"):
            assert word not in low, (word, value)
    # «Кто кого» — длинное тире с неразрывным пробелом перед ним.
    assert " —" in msg.CLIENT_START_ENTRY_GAME
    assert msg.CLIENT_START_ENTRY_APP.endswith(".")


# ---------- cmd_start ----------


def _tid() -> int:
    return 7_500_000_000 + (uuid.uuid4().int % 100_000_000)


def _message(payload: str) -> MagicMock:
    message = MagicMock()
    message.text = f"/start {payload}".rstrip()
    message.from_user = MagicMock(id=_tid(), username="entry_user")
    message.answer = AsyncMock()
    return message


def _button(message: MagicMock):
    markup = message.answer.await_args.kwargs["reply_markup"]
    rows = markup.inline_keyboard
    assert len(rows) == 1 and len(rows[0]) == 1
    return rows[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "param, path",
    [
        ("trainer_7_s_55_v_p3", "client-home"),
        ("trainer_7_i_request", "client-home"),
        ("follow_arena_3", "client-home"),
        ("company_9", "client-home"),
        ("kkm_5", "client-home"),
        ("kks_insta", "kto-kogo"),
        ("kkn_42_h", "client-home"),
        ("unknown_thing", "client-home"),
    ],
)
async def test_cmd_start_answers_with_one_button(monkeypatch, param, path) -> None:
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    message = _message(param)
    await client_handlers.cmd_start(message)
    assert message.answer.await_count == 1
    button = _button(message)
    assert button.web_app.url == f"{BASE}/webapp/{path}?startapp={param}"
    assert message.answer.await_args.args[0] in (msg.CLIENT_START_ENTRY_APP, msg.CLIENT_START_ENTRY_GAME)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["", "bad param!", "x" * 70])
async def test_cmd_start_invalid_or_empty_gets_welcome(monkeypatch, payload) -> None:
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    message = _message(payload)
    await client_handlers.cmd_start(message)
    message.answer.assert_awaited_once_with(msg.CLIENT_START_WELCOME)


@pytest.mark.asyncio
async def test_cmd_start_without_https_keeps_welcome(monkeypatch) -> None:
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url="http://localhost:8000"))
    message = _message("trainer_7")
    await client_handlers.cmd_start(message)
    message.answer.assert_awaited_once_with(msg.CLIENT_START_WELCOME)


@pytest.mark.asyncio
async def test_cmd_start_send_failure_does_not_raise(monkeypatch) -> None:
    monkeypatch.setattr(client_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    message = _message("trainer_7")
    message.answer = AsyncMock(side_effect=TelegramForbiddenError(method=MagicMock(), message="bot was blocked by the user"))
    await client_handlers.cmd_start(message)  # не падает
    assert message.answer.await_count == 1


def test_universal_branch_is_the_last_one_in_cmd_start() -> None:
    """Все особые ветки разбирают параметр раньше универсальной."""
    source = inspect.getsource(client_handlers.cmd_start)
    universal = source.index("start_entry_reply(")
    for marker in (
        "handle_winter_start(",
        "parse_suggest_start(",
        "_parse_welcome_t_token(",
        "parse_bell_start(",
        "parse_watch_start(",
        "is_catalog_deep_link(",
        'payload.startswith("col_")',
        "_parse_cert_start(",
        "SHARE_REF_PREFIX",
        "_parse_trainer_preview(",
        "WELCOME_REF_PREFIX",
        "_parse_pass_start(",
        "_parse_client_start(",
    ):
        assert source.index(marker) < universal, marker
    assert source.index("msg.CLIENT_START_WELCOME)\n", universal) > universal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload, expected",
    [
        ("mbell_99999999", "welcome"),  # матча нет — своя ветка отвечает приветствием
        ("watch_999999999", "welcome"),  # катка нет — своя ветка отвечает приветствием
        ("cert_NOPE1234", "cert_invalid"),
        ("arena_999999999", "catalog"),
        ("catalog", "catalog"),
        ("welcome_ref_999999999", "trainer_missing"),
        ("sg_" + "a" * 20, "suggest"),
        ("col_no-such-studio", "welcome"),
        ("wnear", "winter"),
    ],
)
async def test_existing_params_stay_on_their_handlers(app_use_test_db, _test_db_core, monkeypatch, payload, expected) -> None:
    spy = MagicMock(wraps=start_entry_reply)
    monkeypatch.setattr(client_handlers, "start_entry_reply", spy)
    monkeypatch.setattr(client_handlers, "async_session_factory", _test_db_core["factory"])
    import src.bot.winter_bot as winter_bot

    monkeypatch.setattr(winter_bot, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setenv("WEBAPP_BASE_URL", BASE)
    monkeypatch.setenv("CLIENT_BOT_USERNAME", BOT)
    message = _message(payload)
    message.answer_photo = AsyncMock()
    await client_handlers.cmd_start(message)
    # Своя ветка ответила сама: универсальная не вызвана либо (ветка не ответила) вернула None.
    assert all(start_entry_reply(*c.args, **c.kwargs) is None for c in spy.call_args_list)
    assert message.answer.await_count >= 1
    sent = message.answer.await_args.args[0]
    assert sent not in (msg.CLIENT_START_ENTRY_APP, msg.CLIENT_START_ENTRY_GAME)
    if expected == "welcome":
        assert sent == msg.CLIENT_START_WELCOME
    elif expected == "cert_invalid":
        assert sent == msg.CLIENT_CERT_CODE_INVALID
    elif expected == "trainer_missing":
        assert sent == msg.CLIENT_ERROR_TRAINER_NOT_FOUND
    elif expected == "suggest":
        assert sent == msg.CLIENT_SUGGEST_LINK_USED
    elif expected == "catalog":
        button = _button(message)
        assert "startapp=" not in button.web_app.url and "/webapp/ice" in button.web_app.url


def test_module_has_no_aiogram() -> None:
    assert not re.search(r"^\s*(from|import) aiogram", inspect.getsource(start_entry), re.M)
