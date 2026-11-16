"""TASK-428: предпросмотр текстов прогрева — получатель только владелец, без базы, без сети в режиме печати;
скрипт «кому уйдёт» только читает."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


mod = _load("warm_preview_send")
OWNER = 1304982166
TOKEN = "123456:SECRET-TOKEN-VALUE"


class Fake:
    def __init__(self, fail=None) -> None:
        self.calls: list[tuple] = []
        self.fail = fail or {}

    async def __call__(self, chat_id, text, buttons, html):
        self.calls.append((chat_id, text, buttons, html))
        err = self.fail.get(len(self.calls))
        if err is not None:
            raise err


async def no_sleep(_):
    return None


def run_main(argv, *, fake=None, monkeypatch, token=TOKEN, inputs=("y",)):
    out: list[str] = []
    fake = fake or Fake()
    made: list[str] = []
    if token is None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN_CLIENT", raising=False)
    else:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN_CLIENT", token)
    answers = list(inputs)

    def make_send(tok):
        made.append(tok)
        return fake

    code = mod.main(argv, input_fn=lambda _: answers.pop(0), make_send=make_send, out=out.append, sleep=no_sleep)
    return code, out, fake, made


def test_constant_is_owner() -> None:
    assert mod.OWNER_TEST_CHAT_ID == OWNER


@pytest.mark.parametrize("bad", [None, 0, -1, OWNER + 1, str(OWNER), True, [OWNER], float(OWNER)])
def test_assert_owner_rejects_everything_else(bad) -> None:
    with pytest.raises(mod.RecipientError):
        mod.assert_owner(bad)
    assert mod.assert_owner(OWNER) == OWNER


def test_print_is_default_and_never_sends(monkeypatch) -> None:
    code, out, fake, made = run_main([], monkeypatch=monkeypatch)
    assert code == 0 and fake.calls == [] and made == []
    assert "ничего не отправлено" in out[-1]


@pytest.mark.parametrize("chat", ["1", "-5", "abc", str(OWNER + 1)])
def test_other_chat_refused_before_anything(monkeypatch, chat) -> None:
    code, out, fake, made = run_main(["--send", "--yes", "--chat-id", chat], monkeypatch=monkeypatch)
    assert code == 2 and fake.calls == [] and made == []


def test_send_only_to_owner_with_confirmation(monkeypatch) -> None:
    code, out, fake, made = run_main(["--send"], monkeypatch=monkeypatch, inputs=("n",))
    assert code == 1 and fake.calls == []
    code, out, fake, made = run_main(["--send"], monkeypatch=monkeypatch)
    assert code == 0 and made == [TOKEN]
    assert fake.calls and {c[0] for c in fake.calls} == {OWNER}
    assert all(TOKEN not in line for line in out)


def test_no_token(monkeypatch) -> None:
    code, out, fake, made = run_main(["--send", "--yes"], monkeypatch=monkeypatch, token=None)
    assert code == 2 and made == []


def test_guard_runs_before_every_call(monkeypatch) -> None:
    calls: list[object] = []
    real = mod.assert_owner

    def spy(chat_id):
        calls.append(chat_id)
        return real(chat_id)

    monkeypatch.setattr(mod, "assert_owner", spy)
    messages = mod.build_messages()
    fake = Fake()
    asyncio.run(mod.deliver(messages, send=fake, sleep=no_sleep, log=lambda *_: None))
    assert len(calls) == len(messages) + 1  # вход и каждая отправка
    with pytest.raises(mod.RecipientError):
        asyncio.run(mod.deliver(messages, send=fake, chat_id=OWNER + 1, sleep=no_sleep))


def test_messages_cover_every_kind_and_buttons_do_nothing() -> None:
    messages = mod.build_messages()
    bodies = [m.text for m in messages if m.html]
    assert any("Ближайшие сеансы" in b for b in bodies)
    assert any(b.startswith("Сегодня на") for b in bodies)
    assert any("сеансы на" in b for b in bodies)
    assert any("Спрашиваем один раз" in b for b in bodies)
    assert all(m.text for m in messages)
    callbacks = {b.get("callback_data") for m in messages for row in m.buttons for b in row}
    assert callbacks == {mod.PREVIEW_CALLBACK}
    assert all("url" not in b for m in messages for row in m.buttons for b in row)


def test_script_has_no_db_or_flag_access() -> None:
    source = (ROOT / "scripts" / "warm_preview_send.py").read_text(encoding="utf-8")
    for forbidden in ("async_session_factory", "Settings(", "WARM_ENABLED", "warm_notices", "dispatch("):
        assert forbidden not in source


def test_audience_script_is_read_only() -> None:
    source = (ROOT / "scripts" / "warm_audience.py").read_text(encoding="utf-8")
    assert "SET TRANSACTION READ ONLY" in source and "commit(" not in source
    for forbidden in ("send_message", "dispatch(", "run_tick", "INSERT", "UPDATE", "DELETE"):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_audience_lists_people_without_names(db_session, monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "tests" / "application"))
    from warm_helpers import ANNA, at, seed_arena, seed_watch

    audience = _load("warm_audience")
    arena = await seed_arena(db_session)
    await seed_watch(db_session, ANNA, arena, created_at=at(8, day=18))
    people = await audience.audience(db_session, now=at(12, day=18))
    assert people["warm_welcome"] == [ANNA] and people["warm_nudge"] == []
    text = audience.render(people, {}, now=at(12, day=18), ids=False, days=7)
    assert str(ANNA) not in text and "warm_welcome: 1" in text
    assert str(ANNA) in audience.render(people, {}, now=at(12, day=18), ids=True, days=7)
