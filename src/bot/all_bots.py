"""Один процесс для трёх Telegram-ботов: админ, тренер, клиент.

Зачем: три отдельных процесса по ~0.25 ГБ каждый почти целиком состоят из одних и тех же импортов.
В одном процессе они занимают столько же, сколько один. Рассылки, планировщик парсеров и OCR остаются
в ``notification_service`` — тяжёлая фоновая работа не мешает ответам ботов.

Каждый бот крутится в своей задаче под супервизором: упал — перезапустится с нарастающей паузой,
остальные продолжают работать. Остановка по SIGTERM/SIGINT общая.

Запуск: ``python -m src.bot.all_bots``. Пока не задана ``ICE_BOTS_ACTIVE=1``, процесс простаивает и
не опрашивает Telegram: так сервис можно создать заранее, не конфликтуя со старыми (на один токен
допустим один опрос), и включить переменной в момент переключения.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import signal
import time
from collections.abc import Awaitable, Callable, Mapping

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

ACTIVE_ENV = "ICE_BOTS_ACTIVE"
START_BACKOFF_SEC = 5.0
MAX_BACKOFF_SEC = 300.0
MIN_STABLE_SEC = 300.0  # дольше этого работал — считаем запуск удачным и сбрасываем паузу


def is_active() -> bool:
    return os.environ.get(ACTIVE_ENV, "").strip().lower() in ("1", "true", "yes")


async def supervise(
    name: str,
    run: Callable[[], Awaitable[None]],
    stop: asyncio.Event,
    *,
    start_backoff: float = START_BACKOFF_SEC,
    max_backoff: float = MAX_BACKOFF_SEC,
    min_stable: float = MIN_STABLE_SEC,
) -> None:
    """Держит ``run`` запущенным до ``stop``: упало — подождать и запустить снова."""
    backoff = start_backoff
    while not stop.is_set():
        started = time.monotonic()
        try:
            await run()
            logger.error("%s: polling ended by itself; restarting", name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s: crashed; restarting", name)
        if stop.is_set():
            return
        if time.monotonic() - started >= min_stable:
            backoff = start_backoff
        logger.warning("%s: restart in %.2fs", name, backoff)
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except TimeoutError:
            pass
        backoff = min(backoff * 2, max_backoff)


async def run_all(
    runners: Mapping[str, Callable[[], Awaitable[None]]],
    stop: asyncio.Event,
    **supervise_kwargs: float,
) -> None:
    """Запускает все боты под супервизором и ждёт ``stop``; затем останавливает их."""
    tasks = [
        asyncio.create_task(supervise(name, run, stop, **supervise_kwargs), name=f"bot-{name}")
        for name, run in runners.items()
    ]
    logger.info("Bots started in one process: %s", ", ".join(runners))
    try:
        await stop.wait()
    finally:
        logger.info("Stopping bots...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Bots stopped.")


async def main() -> None:
    if not is_active():
        logger.warning(
            "%s is not set to 1: idle, Telegram is NOT being polled. "
            "Set it when the separate bot services are stopped.",
            ACTIVE_ENV,
        )
        await asyncio.Event().wait()
        return

    # Импорты здесь, а не наверху: в режиме простоя процесс остаётся лёгким.
    from src.bot import admin_app, client_app, trainer_app
    from src.shared.config import Settings
    from src.shared.sentry_init import init_sentry

    init_sentry(Settings(), "bots")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows / не главный поток
            pass
    runners = {
        "admin": functools.partial(admin_app.main, embedded=True),
        "trainer": functools.partial(trainer_app.main, embedded=True),
        "client": functools.partial(client_app.main, embedded=True),
    }
    await run_all(runners, stop)


if __name__ == "__main__":
    asyncio.run(main())
