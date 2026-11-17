#!/usr/bin/env python3
"""Отправить ВЛАДЕЛЬЦУ тексты прогрева посетителей катков в Telegram, чтобы принять их глазами (TASK-428).

Единственный допустимый получатель — ``OWNER_TEST_CHAT_ID``. Любой другой chat_id (аргумент, строка, ``None``, 0,
отрицательный, bool) — ошибка до отправки; проверка стоит и на входе, и прямо перед каждым вызовом Telegram.
Скрипт не подключается к базе, не пишет в таблицы, не зовёт допуск и не читает флаги рассылки.

По умолчанию (и с ``--print-only``) ничего не шлёт: печатает все сообщения в консоль. Отправка — только с ``--send``,
токен клиентского бота — из ``TELEGRAM_BOT_TOKEN_CLIENT`` (в проде: ``railway run -s <сервис> -- python
scripts/warm_preview_send.py --send``). Токен не печатается.

Для каждого сценария — служебная подпись простым текстом («№ · повод · кому · когда») и само сообщение так, как оно
уйдёт (ParseMode.HTML, те же подписи кнопок). У кнопок ``callback_data`` одна — ``warm:preview``: обработчика нет,
нажатие ничего не меняет. Кнопка «Открыть расписание» здесь тоже callback, без ссылки.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.application import warm_texts as wt  # noqa: E402
from src.application.kk_notify_texts import typo  # noqa: E402
from src.shared.copy_ru import t  # noqa: E402

# Единственный получатель. Никаких списков, масок и чтения из базы или окружения.
OWNER_TEST_CHAT_ID = 1304982166
PAUSE_SEC = 1.2
MAX_RETRIES = 3
PREVIEW_CALLBACK = "warm:preview"
HEADER = (
    "Тестовая рассылка текстов прогрева посетителей катков. Это примеры, кнопки не работают. Отправлено только вам."
)
MINSK = ZoneInfo("Europe/Minsk")
# Четверг, 9:30 по Минску — утро, в которое уходят «сегодня» и «неделя».
NOW = datetime(2026, 11, 19, 9, 30, tzinfo=MINSK)


class RecipientError(Exception):
    """Получатель не владелец: ничего не отправляем."""


class SendStopped(Exception):
    pass


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
    html: bool


def _cb(label: str) -> dict:
    return {"text": label, "callback_data": PREVIEW_CALLBACK}


def _schedule_buttons() -> list[list[dict]]:
    return [[_cb(t("warm.btn.schedule"))], [_cb(t("warm.btn.off"))]]


def _at(days: int, hour: int, minute: int = 0) -> datetime:
    return (NOW + timedelta(days=days)).replace(hour=hour, minute=minute)


_SUB = "подписчику катка (подписка на новые сеансы)"
_MORNING = (
    "утром 9:00–11:00, в бюджете (не больше 1 в день и 3 в неделю вместе с игрой); "
    "игроку в день матча не уходит — день за игрой"
)


def scenarios() -> list[tuple[str, str, str, str, list[list[dict]]]]:
    """(повод, кому, когда, текст, кнопки). Тексты — те же функции, что у настоящих сообщений."""
    chizh, arena = "Чижовка-арена", "ЛД «Гранд Каньон Айс»"
    return [
        (
            "после подписки, два ближайших сеанса",
            _SUB,
            "в течение двух суток после подписки, один раз на человека; ближайших сеансов нет — не пишем",
            wt.welcome_text(arena_name=chizh, starts=[_at(0, 19, 30), _at(2, 12)], now=NOW) or "",
            _schedule_buttons(),
        ),
        (
            "после подписки, один ближайший сеанс",
            _SUB,
            "то же",
            wt.welcome_text(arena_name=arena, starts=[_at(4, 15, 30)], now=NOW) or "",
            _schedule_buttons(),
        ),
        (
            "сегодня лёд, один сеанс",
            _SUB,
            f"{_MORNING}; до сеанса не меньше часа; «сегодня лёд» — не чаще 2 раз за 7 суток",
            wt.today_text(arena_name=chizh, starts=[_at(0, 19, 30)], now=NOW) or "",
            _schedule_buttons(),
        ),
        (
            "сегодня лёд, много сеансов",
            _SUB,
            f"{_MORNING}; больше четырёх сеансов — «и ещё N»",
            wt.today_text(arena_name=chizh, starts=[_at(0, h) for h in (11, 12, 14, 16, 18, 20)], now=NOW) or "",
            _schedule_buttons(),
        ),
        (
            "сеансы на неделю",
            _SUB,
            f"по четвергам, {_MORNING}; только если есть что показать",
            wt.week_text(
                arena_name=chizh,
                starts=[_at(0, 19, 30), _at(1, 18), _at(2, 12), _at(2, 15, 30), _at(3, 12), _at(5, 19)],
                now=NOW,
            )
            or "",
            _schedule_buttons(),
        ),
        (
            "одно напоминание",
            "запускал бота, был в каталоге Mini App один день, смотрел каток, ни на что не подписан",
            "через 3–7 дней после визита, утром; один раз за всё время, без ответа — тишина",
            wt.nudge_text(arena_name=chizh),
            [[_cb(t("warm.btn.subscribe"))], [_cb(t("warm.btn.off"))]],
        ),
    ]


EXTRA = (
    ("ответ на «Не присылать»", "нажавшему «Не присылать»", "всплывающее окно; под сообщением остаётся «Присылать»",
     "warm.off_done", "warm.btn.on"),
    ("ответ на «Присылать»", "нажавшему «Присылать»", "всплывающее окно; под сообщением остаётся «Не присылать»",
     "warm.on_done", "warm.btn.off"),
)  # fmt: skip


def offer_text() -> str:
    """Плашка на карточке катка (на сайте и в Mini App) — не сообщение бота, показана для приёмки слов."""
    return "\n".join(
        [
            f"<b>{t('watch_offer.title')}</b>",
            t("watch_offer.note"),
            f"Кнопки: «{t('watch_offer.cta')}» (Mini App) или «{t('watch_offer.cta_site')}» (сайт), «{t('watch_offer.close')}».",
            f"После подписки в Mini App: {t('watch_offer.done')}",
        ]
    )


def build_messages() -> list[Message]:
    messages = [Message(0, HEADER, [], False)]
    number = 0
    for name, who, when, body, buttons in scenarios():
        number += 1
        messages.append(Message(number, f"{number} · {name} · {who} · {when}", [], False))
        messages.append(Message(number, body, buttons, True))
    for name, who, when, text_key, button_key in EXTRA:
        number += 1
        messages.append(Message(number, f"{number} · {name} · {who} · {when}", [], False))
        messages.append(Message(number, typo(t(text_key)), [[_cb(t(button_key))]], True))
    number += 1
    messages.append(
        Message(
            number,
            f"{number} · предложение подписки на карточке катка · один раз на человека и каток, не подписанным · "
            "после 12 секунд на карточке",
            [],
            False,
        )
    )
    messages.append(Message(number, offer_text(), [], True))
    return messages


def render_console(messages: list[Message]) -> str:
    lines: list[str] = []
    total = len(messages)
    for index, m in enumerate(messages, start=1):
        kind = "заголовок" if m.scenario == 0 else f"сценарий {m.scenario}, {'сообщение' if m.html else 'подпись'}"
        lines.append(f"--- [{index}/{total}] {kind}\n{m.text.replace('<b>', '**').replace('</b>', '**')}")
        if m.buttons:
            lines.append("    кнопки: " + " | ".join(" / ".join(b["text"] for b in row) for row in m.buttons))
        lines.append("")
    return "\n".join(lines)


async def deliver(messages, *, send, chat_id=OWNER_TEST_CHAT_ID, sleep=asyncio.sleep, log=print) -> int:
    """Отправить по порядку. ``send(chat_id, text, buttons, html)``. Возвращает число отправленных."""
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


def _scrub(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    token = os.environ.get("TELEGRAM_BOT_TOKEN_CLIENT", "")
    return text.replace(token, "***") if token else text


def make_telegram_send(token: str):
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
    p = argparse.ArgumentParser(description="Отправить владельцу тексты прогрева посетителей (только ему).")
    p.add_argument("--send", action="store_true", help="отправить в Telegram (по умолчанию — только печать)")
    p.add_argument("--print-only", action="store_true", help="только печать, без сети (по умолчанию)")
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
        out("Ошибка: не задан TELEGRAM_BOT_TOKEN_CLIENT")
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
