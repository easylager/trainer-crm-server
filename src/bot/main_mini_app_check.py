"""
Проверка «Main Mini App» клиентского бота через Bot API ``getMe`` (TASK-223 / P1-5).

Зачем. ``Settings.client_bot_main_mini_app`` по умолчанию ``True``: ссылки шаринга уходят в
``https://t.me/<bot>?startapp=arena_X_s_Y``. Если в BotFather → Main Mini App ничего не
настроено, Telegram такую ссылку не открывает как мини-апп, и карточка молча не появляется.
Настройка живёт у Telegram, не в нашем конфиге, поэтому спрашиваем у него.

Что умеет Bot API. Поле ``User.has_main_web_app`` (Bot API 7.8, 31.07.2024) возвращается
только в ``getMe``: ``true``, если у бота есть Main Mini App
(https://core.telegram.org/bots/api#user). Отдельного метода «прочитать Main Mini App»
нет, поэтому проверяем наличие, а не совпадение URL с нашим доменом.

Модуль не бросает исключений: любая сетевая беда — ``state="unknown"``. Токен в
``detail`` и в лог не попадает (aiohttp кладёт URL с токеном в текст ошибок, поэтому
пишем только имя класса исключения).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import aiohttp

logger = logging.getLogger(__name__)

MainMiniAppState = Literal["enabled", "disabled", "unknown"]

CHECK_TIMEOUT_SEC = 5.0
_BOT_API_BASE = "https://api.telegram.org"
#: Поля, которые Bot API отдаёт только в ``getMe``. Есть хотя бы одно — ответ настоящий,
#: и отсутствие ``has_main_web_app`` значит «не включено», а не «ответ не того вида».
_GET_ME_ONLY_FIELDS = ("can_join_groups", "can_read_all_group_messages", "supports_inline_queries")


@dataclass(frozen=True)
class CheckResult:
    """``ok`` — нет явного расхождения с ожиданием; ``unknown`` не считается провалом.

    ``ok=False`` только когда ждали Main Mini App (``expected=True``), а Telegram говорит,
    что его нет. Чтобы отличить «зелёное» от «не знаем», смотрите ``state``.
    """

    ok: bool
    state: MainMiniAppState
    detail: str


def evaluate_get_me(payload: Any, *, expected: bool) -> CheckResult:
    """Чистая часть: разбор JSON-ответа ``getMe``. Не ходит в сеть, не бросает."""
    if not isinstance(payload, dict):
        return CheckResult(True, "unknown", "ответ getMe не JSON-объект")
    if payload.get("ok") is not True:
        description = str(payload.get("description") or "ok=false")[:120]
        return CheckResult(True, "unknown", f"Bot API: {description}")
    result = payload.get("result")
    if not isinstance(result, dict):
        return CheckResult(True, "unknown", "в ответе getMe нет result")

    flag = result.get("has_main_web_app")
    if isinstance(flag, bool):
        state: MainMiniAppState = "enabled" if flag else "disabled"
        detail = "has_main_web_app=true" if flag else "has_main_web_app=false"
    elif flag is None and any(k in result for k in _GET_ME_ONLY_FIELDS):
        # Telegram может не присылать false у необязательных полей.
        state, detail = "disabled", "has_main_web_app не вернулся (считаем false)"
    else:
        return CheckResult(True, "unknown", "поле has_main_web_app не распознано")

    if expected and state == "disabled":
        return CheckResult(
            False,
            state,
            f"{detail}: BotFather → Main Mini App не настроен, ссылки ?startapp= не откроют карточку",
        )
    if not expected and state == "enabled":
        return CheckResult(True, state, f"{detail}: CLIENT_BOT_MAIN_MINI_APP=false, ссылки идут через /start")
    return CheckResult(True, state, detail)


async def check_main_mini_app(
    bot_token: str,
    *,
    expected: bool,
    timeout_sec: float = CHECK_TIMEOUT_SEC,
    session: aiohttp.ClientSession | None = None,
) -> CheckResult:
    """``getMe`` → есть ли у бота Main Mini App. Никогда не бросает."""
    token = (bot_token or "").strip()
    if not token:
        return CheckResult(True, "unknown", "токен клиентского бота не задан")
    url = f"{_BOT_API_BASE}/bot{token}/getMe"
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    try:
        if session is not None:
            return await _fetch_and_evaluate(session, url, expected=expected, timeout=timeout)
        async with aiohttp.ClientSession(timeout=timeout) as own:
            return await _fetch_and_evaluate(own, url, expected=expected, timeout=timeout)
    except TimeoutError:
        return CheckResult(True, "unknown", "таймаут getMe")
    except Exception as exc:  # noqa: BLE001 — best-effort; текст ошибки может содержать токен
        return CheckResult(True, "unknown", f"getMe не удался: {type(exc).__name__}")


async def _fetch_and_evaluate(
    session: aiohttp.ClientSession,
    url: str,
    *,
    expected: bool,
    timeout: aiohttp.ClientTimeout,
) -> CheckResult:
    async with session.get(url, timeout=timeout) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:  # noqa: BLE001
            return CheckResult(True, "unknown", f"getMe: HTTP {resp.status}, не JSON")
        if resp.status != 200 and not isinstance(data, dict):
            return CheckResult(True, "unknown", f"getMe: HTTP {resp.status}")
        return evaluate_get_me(data, expected=expected)


def format_health_line(result: CheckResult | None) -> str:
    """Строка для ``/version``: ``Main Mini App: ok`` / ``warn`` / ``unknown``."""
    if result is None or result.state == "unknown":
        suffix = f" — {result.detail}" if result is not None else ""
        return f"• Main Mini App: unknown{suffix}"
    if not result.ok:
        return f"• Main Mini App: warn — {result.detail}"
    return "• Main Mini App: ok"


async def warn_if_main_mini_app_missing(bot_token: str, *, expected: bool) -> CheckResult:
    """Старт клиентского бота: WARNING в лог (и Sentry), если ждали Main Mini App, а его нет."""
    result = await check_main_mini_app(bot_token, expected=expected)
    if not result.ok:
        logger.warning("Client bot: Main Mini App check failed — %s", result.detail)
        _capture_sentry_message(f"Client bot Main Mini App disabled: {result.detail}")
    elif result.state == "unknown":
        logger.info("Client bot: Main Mini App state unknown — %s", result.detail)
    else:
        logger.info("Client bot: Main Mini App state=%s", result.state)
    return result


def _capture_sentry_message(text: str) -> None:
    try:
        import sentry_sdk

        sentry_sdk.capture_message(text, level="warning")
    except Exception:  # noqa: BLE001 — Sentry не должен ронять старт бота
        logger.debug("sentry capture_message failed", exc_info=True)
