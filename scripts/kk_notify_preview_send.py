#!/usr/bin/env python3
"""Отправить ВЛАДЕЛЬЦУ тексты уведомлений «Кто кого» в Telegram, чтобы увидеть их глазами (TASK-426).

Единственный допустимый получатель — ``OWNER_TEST_CHAT_ID``. Любой другой chat_id (аргумент, список, строка, ``None``,
0, отрицательный) — ошибка до отправки; проверка стоит и на входе, и прямо перед каждым вызовом Telegram.
Скрипт не подключается к базе, не пишет в таблицы, не зовёт допуск и не читает флаги рассылки.

По умолчанию (и с ``--print-only``) ничего не шлёт: печатает все сообщения в консоль. Отправка — только с ``--send``,
токен клиентского бота — из ``TELEGRAM_BOT_TOKEN_CLIENT`` (в проде: ``railway run -s <сервис> -- python
scripts/kk_notify_preview_send.py --send``). Токен не печатается и не логируется.

Для каждого сценария уходят два сообщения подряд: служебная подпись простым текстом («№ · повод · кому · когда») и само
сообщение так, как оно уйдёт игроку (ParseMode.HTML, те же кнопки). У кнопок ``callback_data`` одна — ``kk:preview``:
обработчика в проде нет, нажатие ничего не меняет.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.application import kk_notify_texts as tx  # noqa: E402
from src.application.hockey_teams import display_name as club_name  # noqa: E402
from src.application.place_links import public_telegram_entry_link  # noqa: E402
from src.shared.copy_ru import t  # noqa: E402

# Единственный получатель. Никаких списков, масок и чтения из базы или окружения.
OWNER_TEST_CHAT_ID = 1304982166
PAUSE_SEC = 1.2
MAX_RETRIES = 3
PREVIEW_CALLBACK = "kk:preview"
HEADER = "Тестовая рассылка текстов «Кто кого». Это примеры, кнопки не работают. Отправлено только вам."


def _load_preview():
    spec = importlib.util.spec_from_file_location("kk_notify_preview", ROOT / "scripts" / "kk_notify_preview.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


PREVIEW = _load_preview()


class RecipientError(Exception):
    """Получатель не владелец: ничего не отправляем."""


def assert_owner(chat_id: object) -> int:
    """Пропускает только ровно ``OWNER_TEST_CHAT_ID`` типа int (не bool, не строка, не список, не None)."""
    if type(chat_id) is not int or chat_id != OWNER_TEST_CHAT_ID:
        raise RecipientError(f"Получатель запрещён: разрешён только чат владельца {OWNER_TEST_CHAT_ID}")
    return chat_id


@dataclass(frozen=True)
class Message:
    scenario: int  # 0 — заголовок
    text: str
    buttons: list[list[dict]]
    html: bool  # True — ParseMode.HTML, False — простой текст (служебная подпись)


# ---------- сценарии ----------

_ACTIVE = "активному игроку (ход за последние 7 суток), согласие есть"
_MORNING = "утром 09:00–11:00"
_SIX = "матч в ближайшие 6 суток, хода на него нет"

# название варианта в предпросмотре -> (повод, кому, когда, матч для кнопок хода или None)
_D, _T, _A, _S, _SP = PREVIEW.DINAMO, PREVIEW.TORPEDO, PREVIEW.AK_BARS, PREVIEW.SOCHI, PREVIEW.SPARTAK
SCENARIOS: dict[str, tuple[str, str, str, tuple[str, str] | None]] = {
    "1. Матч сегодня": (
        "матч сегодня",
        f"{_ACTIVE}, хода на матч нет",
        f"{_MORNING}, до матча не меньше 3 часов",
        (_D, _T),
    ),
    "1. Матч завтра": (
        "матч завтра",
        f"{_ACTIVE}, хода на матч нет",
        f"{_MORNING}, до матча не меньше 3 часов",
        (_D, _T),
    ),
    "2. Возврат, 3 дня": ("возврат, 3 дня", f"игроку 3 суток без хода; {_SIX}", _MORNING, (_D, _A)),
    "2. Возврат, 10 дней, место есть": (
        "возврат, 10 дней, со строкой места",
        f"игроку 10 суток без хода; {_SIX}; он в верхней половине таблицы месяца, участников не меньше 5",
        _MORNING,
        (_D, _A),
    ),
    "2. Возврат, 10 дней, место не называем (нижняя половина)": (
        "возврат, 10 дней, без места",
        f"игроку 10 суток без хода; {_SIX}; он в нижней половине таблицы или участников меньше 5, строки места нет",
        _MORNING,
        (_D, _A),
    ),
    "2. Возврат, 30 дней": (
        "возврат, 30 дней",
        f"игроку 30 суток без хода (последняя попытка, дальше возвратов нет); {_SIX}",
        _MORNING,
        (_D, _S),
    ),
    "3. Итог недели, место и матч": (
        "итог недели, место и матч",
        f"{_ACTIVE}: за неделю есть засчитанный ход и очков больше нуля; на ближайший матч хода нет",
        "по понедельникам 09:00–11:00, не 1-го числа",
        (_D, _SP),
    ),
    "3. Итог недели, место, без строки матча": (
        "итог недели, место, без матча",
        f"{_ACTIVE}: за неделю есть очки; на ближайший матч ход уже сделан или матча нет",
        "по понедельникам 09:00–11:00, не 1-го числа",
        None,
    ),
    "3. Итог недели, места нет (мало участников)": (
        "итог недели, без места",
        f"{_ACTIVE}: за неделю есть очки; он не в верхней половине таблицы или участников меньше 5",
        "по понедельникам 09:00–11:00, не 1-го числа",
        (_D, _SP),
    ),
    "3. Итог недели, 1 ход и 11 очков": (
        "итог недели, 1 ход и 11 очков",
        f"{_ACTIVE}: один засчитанный ход за неделю (проверка склонений)",
        "по понедельникам 09:00–11:00, не 1-го числа",
        None,
    ),
    "3. Итог недели, 21 ход и 105 очков": (
        "итог недели, 21 ход и 105 очков",
        f"{_ACTIVE}: 21 засчитанный ход за неделю (проверка склонений)",
        "по понедельникам 09:00–11:00, не 1-го числа",
        None,
    ),
}
_MONTH_WHO = "игроку с засчитанными очками за месяц; месяц закрыт, правок итога нет"
_MONTH_WHEN = "1-го числа с 10:00 (если не ушло — 2-го до 11:00)"
for _title, _name, _extra, _match in (
    (
        "4. Месяц без короны, место",
        "итог месяца, без короны, с местом",
        "он в верхней половине таблицы, участников не меньше 5",
        (_D, _S),
    ),
    (
        "4. Месяц без короны, места нет",
        "итог месяца, без короны, без места",
        "места не называем (нижняя половина или мало участников)",
        (_D, _S),
    ),
    (
        "4. Месяц без «в точку»",
        "итог месяца, без «в точку»",
        "ни одного хода в точку: клауза «в точку» не пишется",
        None,
    ),
    ("4. Корона одному", "итог месяца, корона одному", "корона за месяц у него одного", (_D, _S)),
    ("4. Корона на двоих", "итог месяца, корона на двоих", "корона за месяц у него и ещё одного игрока", (_D, _S)),
    ("4. Корона общая, трое", "итог месяца, корона общая (трое)", "корона за месяц у него и ещё двоих", (_D, _S)),
    ("4. Корона общая, шестеро", "итог месяца, корона общая (шестеро)", "корона за месяц у него и ещё пятерых", None),
):
    SCENARIOS[_title] = (_name, f"{_MONTH_WHO}; {_extra}", _MONTH_WHEN, _match)
CONSENT = (
    "5. Согласие после первого хода",
    "вопрос о согласии",
    "игроку после первого хода, согласия ещё нет",
    "в тот же день вне тихих часов 23:00–09:00",
)
EXTRA = (
    ("ответ на «Не присылать»", "игроку, нажавшему «Не присылать»", "сразу после нажатия (всплывающее окно; под сообщением остаётся «Присылать»)", "kk_notify.off_done", "kk_notify.btn.yes"),
    ("ответ на «Присылать»", "игроку, нажавшему «Присылать»", "сразу после нажатия (всплывающее окно; под сообщением остаётся «Не присылать»)", "kk_notify.on_done", "kk_notify.btn.no"),
)  # fmt: skip


class _LinkSettings:
    """Только то, что нужно для ссылки «Таблица»; без чтения ``.env``, базы и флагов рассылки."""

    def __init__(self) -> None:
        env = os.environ.get
        self.public_entry_via_start = env("PUBLIC_ENTRY_VIA_START", "").strip().lower() in ("1", "true", "yes", "on")
        self.client_bot_username = env("CLIENT_BOT_USERNAME") or None
        self.client_mini_app_short_name = env("CLIENT_MINI_APP_SHORT_NAME") or None
        self.client_bot_main_mini_app = env("CLIENT_BOT_MAIN_MINI_APP", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )


def table_button() -> dict:
    """«Таблица» — URL-кнопка, как в настоящем сообщении (но без номера настоящего матча: просто вход в игру)."""
    url = public_telegram_entry_link(_LinkSettings(), start_param="kkn") or "https://t.me/kk_preview_bot?start=kkn"
    return {"text": t("kk_notify.btn.table"), "url": url}


def _cb(label: str) -> dict:
    return {"text": label, "callback_data": PREVIEW_CALLBACK}


def match_buttons(match: tuple[str, str] | None) -> list[list[dict]]:
    """Те же ряды, что у настоящих сообщений: кнопки хода (названия команд), «Таблица», «Не присылать»."""
    rows: list[list[dict]] = []
    if match is not None:
        rows.append([_cb(club_name(match[0])), _cb(club_name(match[1]))])
    rows.append([table_button()])
    rows.append([_cb(t("kk_notify.btn.no"))])
    return rows


def build_messages() -> list[Message]:
    """Заголовок и пары «подпись + сообщение» по всем сценариям. Тексты — те же функции рендера, что у настоящих."""
    messages = [Message(0, HEADER, [], False)]
    number = 0
    rendered = dict(PREVIEW.render_all())
    for title, body in rendered.items():
        if title == CONSENT[0]:
            continue
        name, who, when, match = SCENARIOS[title]
        number += 1
        messages.append(Message(number, f"{number} · {name} · {who} · {when}", [], False))
        messages.append(Message(number, body, match_buttons(match), True))
    number += 1
    messages.append(Message(number, f"{number} · {CONSENT[1]} · {CONSENT[2]} · {CONSENT[3]}", [], False))
    messages.append(
        Message(number, rendered[CONSENT[0]], [[_cb(t("kk_notify.btn.yes")), _cb(t("kk_notify.btn.no"))]], True)
    )
    for name, who, when, text_key, button_key in EXTRA:
        number += 1
        messages.append(Message(number, f"{number} · {name} · {who} · {when}", [], False))
        messages.append(Message(number, tx.typo(t(text_key)), [[_cb(t(button_key))]], True))
    return messages


def render_console(messages: list[Message]) -> str:
    lines: list[str] = []
    total = len(messages)
    for index, m in enumerate(messages, start=1):
        kind = "заголовок" if m.scenario == 0 else f"сценарий {m.scenario}, {'сообщение' if m.html else 'подпись'}"
        text = m.text.replace("<b>", "**").replace("</b>", "**")
        lines.append(f"--- [{index}/{total}] {kind}\n{text}")
        if m.buttons:
            shown = " | ".join(" / ".join(b["text"] for b in row) for row in m.buttons)
            lines.append(f"    кнопки: {shown}")
        lines.append("")
    return "\n".join(lines)


# ---------- отправка ----------


async def deliver(messages, *, send, chat_id=OWNER_TEST_CHAT_ID, sleep=asyncio.sleep, log=print) -> int:
    """Отправить сообщения по порядку. ``send(chat_id, text, buttons, html)``. Возвращает число отправленных."""
    assert_owner(chat_id)  # проверка на входе
    sent = 0
    for index, m in enumerate(messages, start=1):
        for attempt in range(MAX_RETRIES + 1):
            assert_owner(chat_id)  # и прямо перед каждым вызовом Telegram
            try:
                await send(chat_id, m.text, m.buttons, m.html)
                break
            except RecipientError:
                raise
            except Exception as exc:  # noqa: BLE001
                wait = getattr(exc, "retry_after", None)
                if wait is not None and attempt < MAX_RETRIES:
                    log(f"Telegram просит подождать {wait} с (повтор {attempt + 1} из {MAX_RETRIES})")
                    await sleep(float(wait) + 0.5)
                    continue
                where = "заголовок" if m.scenario == 0 else f"сценарий {m.scenario}"
                raise SendStopped(
                    f"Остановлено: {where}, сообщение {index} из {len(messages)}: {_scrub(exc)}"
                ) from None
        sent += 1
        if index < len(messages):
            await sleep(PAUSE_SEC)
    return sent


class SendStopped(Exception):
    pass


def _scrub(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    token = os.environ.get("TELEGRAM_BOT_TOKEN_CLIENT", "")
    return text.replace(token, "***") if token else text


def make_telegram_send(token: str):
    """Отправитель через клиентского бота. aiogram подключается только здесь, при настоящей отправке."""
    from aiogram import Bot
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    bot = Bot(token=token)

    async def send(chat_id, text, buttons, html):
        markup = (
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in buttons])
            if buttons
            else None
        )
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML" if html else None)

    send.close = bot.session.close  # type: ignore[attr-defined]
    return send


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Отправить владельцу тексты уведомлений «Кто кого» (только ему).")
    p.add_argument("--send", action="store_true", help="отправить в Telegram (по умолчанию — только печать)")
    p.add_argument("--print-only", action="store_true", help="только печать в консоль, без сети (по умолчанию)")
    p.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    p.add_argument("--chat-id", default=None, help=f"необязательно; допустимо только {OWNER_TEST_CHAT_ID}")
    return p.parse_args(argv)


def main(
    argv: list[str] | None = None, *, input_fn=input, make_send=make_telegram_send, out=print, sleep=asyncio.sleep
) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    chat_id: object = OWNER_TEST_CHAT_ID
    if args.chat_id is not None:
        try:
            chat_id = int(str(args.chat_id).strip())
        except ValueError:
            out(f"Ошибка: получатель запрещён, разрешён только чат владельца {OWNER_TEST_CHAT_ID}")
            return 2
    try:
        assert_owner(chat_id)
    except RecipientError as exc:
        out(f"Ошибка: {exc}")
        return 2
    messages = build_messages()
    if args.print_only or not args.send:
        out(render_console(messages))
        out(f"Режим печати: {len(messages)} сообщений, ничего не отправлено.")
        return 0
    token = (os.environ.get("TELEGRAM_BOT_TOKEN_CLIENT") or "").strip()
    if not token:
        out(
            "Ошибка: не задан TELEGRAM_BOT_TOKEN_CLIENT (для прода: railway run -s <сервис> -- python scripts/kk_notify_preview_send.py --send)"
        )
        return 2
    if (
        not args.yes
        and input_fn(f"Отправить {len(messages)} сообщений в чат {OWNER_TEST_CHAT_ID}? [y/N] ").strip().lower() != "y"
    ):
        out("Отменено, ничего не отправлено.")
        return 1
    send = make_send(token)

    async def run() -> int:
        try:
            return await deliver(messages, send=send, chat_id=chat_id, sleep=sleep, log=out)
        finally:
            close = getattr(send, "close", None)
            if close is not None:
                await close()

    try:
        count = asyncio.run(run())
    except (RecipientError, SendStopped) as exc:
        out(str(exc))
        return 3
    out(f"Отправлено {count} сообщений в чат {OWNER_TEST_CHAT_ID}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
