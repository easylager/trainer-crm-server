"""TASK-426: скрипт отправки текстов владельцу — получатель только владелец, без базы, без сети в режиме печати."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "kk_notify_preview_send.py"
spec = importlib.util.spec_from_file_location("kk_notify_preview_send_under_test", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

OWNER = 1304982166
TOKEN = "123456:SECRET-TOKEN-VALUE"


class Fake:
    """Подменный отправитель: запоминает вызовы."""

    def __init__(self, fail=None) -> None:
        self.calls: list[tuple] = []
        self.fail = fail or {}

    async def __call__(self, chat_id, text, buttons, html):
        self.calls.append((chat_id, text, buttons, html))
        err = self.fail.get(len(self.calls))
        if err is not None:
            raise err


class Retry(Exception):
    def __init__(self, retry_after) -> None:
        super().__init__("flood")
        self.retry_after = retry_after


async def no_sleep(_):
    return None


def run_main(argv, *, fake=None, token=TOKEN, monkeypatch=None, inputs=("y",)):
    out: list[str] = []
    sleeps: list[float] = []
    fake = fake or Fake()
    made: list[str] = []

    async def sleeper(sec):
        sleeps.append(sec)

    def make_send(tok):
        made.append(tok)
        return fake

    answers = iter(inputs)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_CLIENT", token) if token else monkeypatch.delenv("TELEGRAM_BOT_TOKEN_CLIENT", raising=False)
    code = mod.main(argv, input_fn=lambda prompt: (out.append(prompt), next(answers))[1], make_send=make_send, out=out.append, sleep=sleeper)
    return code, out, fake, sleeps, made


# ---------- 1. охрана получателя ----------

BAD_IDS = [0, -1, -OWNER, OWNER + 1, "1304982166", None, [OWNER], (OWNER,), True, float(OWNER), {OWNER}, "", b"1304982166"]


@pytest.mark.parametrize("bad", BAD_IDS, ids=repr)
def test_only_the_owner_chat_passes_the_guard(bad) -> None:
    with pytest.raises(mod.RecipientError):
        mod.assert_owner(bad)
    fake = Fake()
    with pytest.raises(mod.RecipientError):
        asyncio.run(mod.deliver(mod.build_messages(), send=fake, chat_id=bad, sleep=no_sleep))
    assert fake.calls == []


def test_owner_constant_and_guard_accept_exactly_the_owner() -> None:
    assert mod.OWNER_TEST_CHAT_ID == OWNER and mod.assert_owner(OWNER) == OWNER


@pytest.mark.parametrize("arg", ["0", "-1", "1304982167", "abc", "[1304982166]", "1304982166,5"])
def test_cli_rejects_other_chat_ids_without_sending(arg, monkeypatch) -> None:
    code, out, fake, _, made = run_main(["--send", "--yes", "--chat-id", arg], monkeypatch=monkeypatch)
    assert code == 2 and fake.calls == [] and made == []
    assert any("запрещён" in line for line in out)


def test_cli_accepts_the_owner_id_argument(monkeypatch) -> None:
    code, _, fake, _, _ = run_main(["--send", "--yes", "--chat-id", str(OWNER)], monkeypatch=monkeypatch)
    assert code == 0 and fake.calls


def test_guard_is_checked_before_every_single_call(monkeypatch) -> None:
    """Даже если получатель «испортился» посреди рассылки, следующий вызов Telegram не происходит."""
    fake = Fake()

    async def corrupting(chat_id, text, buttons, html):
        await fake(chat_id, text, buttons, html)
        monkeypatch.setattr(mod, "OWNER_TEST_CHAT_ID", 1)

    with pytest.raises(mod.RecipientError):
        asyncio.run(mod.deliver(mod.build_messages(), send=corrupting, sleep=no_sleep))
    assert len(fake.calls) == 1


# ---------- 2. печать не трогает сеть ----------


@pytest.mark.parametrize("argv", [["--print-only"], [], ["--print-only", "--yes"]])
def test_print_only_is_default_and_never_calls_network(argv, monkeypatch) -> None:
    def boom(_):
        raise AssertionError("в режиме печати отправитель создаваться не должен")

    out: list[str] = []
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_CLIENT", raising=False)
    code = mod.main(argv, input_fn=boom, make_send=boom, out=out.append, sleep=no_sleep)
    assert code == 0 and "ничего не отправлено" in out[-1]


# ---------- 3. содержимое = рендер настоящих функций ----------


def test_every_sent_body_matches_the_renderer(monkeypatch) -> None:
    code, out, fake, sleeps, made = run_main(["--send", "--yes"], monkeypatch=monkeypatch)
    assert code == 0 and made == [TOKEN]
    messages = mod.build_messages()
    assert [(c[1], c[3]) for c in fake.calls] == [(m.text, m.html) for m in messages]
    assert all(c[0] == OWNER for c in fake.calls)
    rendered = [body for _, body in mod.PREVIEW.render_all()]
    html_bodies = [c[1] for c in fake.calls if c[3]]
    for body in rendered:
        assert body in html_bodies
    assert len(sleeps) == len(messages) - 1 and set(sleeps) == {1.2}  # пауза между сообщениями


def test_header_first_and_caption_message_pairs(monkeypatch) -> None:
    _, _, fake, _, _ = run_main(["--send", "--yes"], monkeypatch=monkeypatch)
    calls = fake.calls
    assert calls[0][1] == "Тестовая рассылка текстов «Кто кого». Это примеры, кнопки не работают. Отправлено только вам."
    assert calls[0][3] is False
    body_calls = calls[1:]
    assert len(body_calls) % 2 == 0
    for i in range(0, len(body_calls), 2):
        caption, message = body_calls[i], body_calls[i + 1]
        assert caption[3] is False and message[3] is True  # подпись простым текстом, сообщение — HTML
        n = i // 2 + 1
        assert re.match(rf"^{n} · [^·]+ · [^·]+ · [^·]+$", caption[1]), caption[1]
        assert "<" not in caption[1] and caption[2] == []


def test_every_preview_variant_is_covered() -> None:
    titles = [t for t, _ in mod.PREVIEW.render_all()]
    assert set(mod.SCENARIOS) | {mod.CONSENT[0]} == set(titles)
    extra = len(mod.EXTRA)
    assert len(mod.build_messages()) == 1 + 2 * (len(titles) + extra)


# ---------- кнопки безопасны ----------


def test_buttons_are_inert_previews() -> None:
    texts = set()
    for m in mod.build_messages():
        for row in m.buttons:
            for b in row:
                texts.add(b["text"])
                if "callback_data" in b:
                    assert b["callback_data"] == "kk:preview"
                else:
                    assert b["url"].startswith("https://t.me/") and b["text"] == "Таблица"
    assert {"Таблица", "Не присылать", "Присылать"} <= texts
    assert not any(re.match(r"^kk:(p|n|yes|noall|off|lv)\b", b.get("callback_data", "")) for m in mod.build_messages() for r in m.buttons for b in r)


def test_return_button_present_in_off_reply() -> None:
    off = [m for m in mod.build_messages() if m.html and "Придут только" in m.text][0]
    assert [b["text"] for row in off.buttons for b in row] == ["Присылать"]
    on = [m for m in mod.build_messages() if m.html and m.text.startswith("Хорошо")][0]
    assert [b["text"] for row in on.buttons for b in row] == ["Не присылать"]


# ---------- токен, подтверждение, ошибки ----------


def test_token_is_never_printed(monkeypatch) -> None:
    fake = Fake(fail={3: RuntimeError(f"boom url=https://api.telegram.org/bot{TOKEN}/sendMessage")})
    code, out, *_ = run_main(["--send", "--yes"], fake=fake, monkeypatch=monkeypatch)
    assert code == 3 and TOKEN not in "\n".join(out) and "***" in "\n".join(out)
    code, out, *_ = run_main(["--send", "--yes"], monkeypatch=monkeypatch)
    assert TOKEN not in "\n".join(out)
    code, out, *_ = run_main(["--print-only"], monkeypatch=monkeypatch)
    assert TOKEN not in "\n".join(out)


def test_missing_token_is_a_clear_error(monkeypatch) -> None:
    code, out, fake, _, made = run_main(["--send", "--yes"], token="", monkeypatch=monkeypatch)
    assert code == 2 and made == [] and fake.calls == [] and "TELEGRAM_BOT_TOKEN_CLIENT" in "\n".join(out)


def test_confirmation_prompt_and_refusal(monkeypatch) -> None:
    code, out, fake, _, made = run_main(["--send"], monkeypatch=monkeypatch, inputs=("n",))
    count = len(mod.build_messages())
    assert code == 1 and fake.calls == [] and made == []
    assert f"Отправить {count} сообщений в чат {OWNER}? [y/N] " in out
    code, _, fake, _, _ = run_main(["--send"], monkeypatch=monkeypatch, inputs=("y",))
    assert code == 0 and len(fake.calls) == count


def test_429_waits_and_retries_then_gives_up_after_three(monkeypatch) -> None:
    fake = Fake(fail={2: Retry(2), 3: Retry(2)})  # второй вызов: два раза 429, потом ок
    code, out, fake, sleeps, _ = run_main(["--send", "--yes"], fake=fake, monkeypatch=monkeypatch)
    assert code == 0 and 2.5 in sleeps
    storm = Fake(fail={i: Retry(1) for i in range(2, 9)})  # шторм: сдаёмся после трёх повторов
    code, out, storm, sleeps, _ = run_main(["--send", "--yes"], fake=storm, monkeypatch=monkeypatch)
    assert code == 3 and len(storm.calls) == 1 + 4  # заголовок + 1 попытка + 3 повтора
    assert any("Остановлено" in line for line in out)


def test_other_error_stops_with_scenario_number(monkeypatch) -> None:
    fake = Fake(fail={6: RuntimeError("Bad Request: chat not found")})  # 6-й вызов = сообщение сценария 3
    code, out, fake, _, _ = run_main(["--send", "--yes"], fake=fake, monkeypatch=monkeypatch)
    assert code == 3 and len(fake.calls) == 6
    assert any("сценарий 3" in line and "сообщение 6" in line for line in out)


# ---------- нет настоящих данных игроков ----------


def test_no_real_player_data_in_any_message() -> None:
    blob = "\n".join(m.text for m in mod.build_messages())
    assert not re.search(r"\d{7,}", blob)  # ни player_key, ни chat_id
    assert "player_key" not in blob and "9420001" not in blob
    names = {"Динамо-Минск", "Торпедо", "Ак Барс", "Сочи", "Спартак"}
    for m in mod.build_messages():
        for row in m.buttons:
            for b in row:
                assert "url" in b or b["text"] in names | {"Не присылать", "Присылать"}


# ---------- без базы ----------


def test_script_does_not_import_database_modules() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "hockey_notices", "kk_notify_gate", "kk_notify_events", "kk_notify_journal", "kk_notify_phase",
        "kk_notify import", "infrastructure", "sqlalchemy", "asyncpg", "psycopg", "async_session", "get_settings",
        "src.shared.config", "hockey_game", "DATABASE_URL",
    ):  # fmt: skip
        assert forbidden not in src, forbidden
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('m', {str(SCRIPT)!r})\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['m'] = m; spec.loader.exec_module(m)\n"
        "m.build_messages()\n"
        "bad = sorted(x for x in sys.modules if x.startswith(('src.infrastructure', 'asyncpg', 'psycopg', 'src.api')))\n"
        "print('BAD', bad)\n"
    )
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert "BAD []" in result.stdout, result.stdout
