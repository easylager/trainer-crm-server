"""
SMTP не должен уметь держать HTTP-запрос дольше своего бюджета.

Выдача сертификата отправляет письмо прямо в обработчике запроса, а ``smtplib.SMTP`` по
умолчанию берёт ``socket._GLOBAL_DEFAULT_TIMEOUT`` — то есть ждёт недоступный хост
бесконечно. Тренер в этот момент смотрит на кнопку «Отправляем…», которая не вернётся
никогда: ``finally`` в клиенте ждёт ответа, которого нет.

Письмо при этом не теряется — неудачная inline-отправка уходит в ``certificate_email_outbox``,
который разбирает ретрай-цикл раз в 2 минуты. Поэтому «не успели» здесь не ошибка, а штатная
ветка: главное, чтобы функция **вернулась**.
"""
from __future__ import annotations

import asyncio
import inspect
import time

import pytest

from src.shared import email_sender
from src.shared.config import Settings


def test_smtp_connection_is_never_opened_without_a_timeout() -> None:
    """Сокетный таймаут — первая линия: без него висит уже connect."""
    src = inspect.getsource(email_sender._send_sync)
    assert "smtplib.SMTP(" in src
    assert "timeout=" in src, "smtplib.SMTP без timeout ждёт недоступный хост бесконечно"


@pytest.mark.asyncio
async def test_a_stalling_smtp_server_does_not_hold_the_request(monkeypatch) -> None:
    """
    Потолок поверх сокета: сокетный таймаут ограничивает отдельные операции, а этот — весь
    разговор. Сервер, отвечающий по байту в секунду, не нарушает ни одного сокетного таймаута
    и всё равно держал бы запрос сколько угодно.
    """
    monkeypatch.setattr(email_sender, "_smtp_configured", lambda: True)

    def never_returns(*args, **kwargs):
        # Дольше бюджета, но недолго само по себе: asyncio не умеет отменять поток, и
        # оставшийся sleep честно дожидается в teardown, удлиняя прогон на ровно столько же.
        time.sleep(3)

    monkeypatch.setattr(email_sender, "_send_sync", never_returns)

    original = Settings()

    class _FastDeadline(Settings):  # type: ignore[misc]
        smtp_inline_deadline_sec: float = 0.3

    monkeypatch.setattr(email_sender, "Settings", _FastDeadline)

    started = time.monotonic()
    sent = await email_sender.send_certificate_pdf_email(
        "recipient@example.com", b"%PDF-1.4 fake", trainer_name="Тренер", code="CERT-1"
    )
    elapsed = time.monotonic() - started

    assert sent is False, "не отправили — значит False, и вызывающий кладёт письмо в очередь"
    assert elapsed < 5, f"запрос держали {elapsed:.1f}s вместо бюджета {original.smtp_inline_deadline_sec}s"


@pytest.mark.asyncio
async def test_the_link_email_is_bounded_the_same_way(monkeypatch) -> None:
    """Вторая точка отправки — та же гарантия: одинаковое правило, а не частный патч."""
    monkeypatch.setattr(email_sender, "_smtp_configured", lambda: True)
    monkeypatch.setattr(email_sender, "_send_sync", lambda *a, **kw: time.sleep(3))

    class _FastDeadline(Settings):  # type: ignore[misc]
        smtp_inline_deadline_sec: float = 0.3
        client_bot_username: str | None = "glide_client_bot"

    monkeypatch.setattr(email_sender, "Settings", _FastDeadline)

    started = time.monotonic()
    sent = await email_sender.send_certificate_link_email("recipient@example.com", "CERT-1")
    assert sent is False
    assert time.monotonic() - started < 5


@pytest.mark.asyncio
async def test_a_working_smtp_still_reports_success(monkeypatch) -> None:
    """Сторож от перекоса: ограничение не должно превращать успешную отправку в «не смогли»."""
    monkeypatch.setattr(email_sender, "_smtp_configured", lambda: True)
    calls: list[str] = []

    def quick(to_email: str, *args, **kwargs):
        calls.append(to_email)

    monkeypatch.setattr(email_sender, "_send_sync", quick)

    sent = await email_sender.send_certificate_pdf_email(
        "recipient@example.com", b"%PDF-1.4 fake", trainer_name="Тренер", code="CERT-1"
    )
    assert sent is True
    assert calls == ["recipient@example.com"]


@pytest.mark.asyncio
async def test_unconfigured_smtp_fails_fast_instead_of_dialling(monkeypatch) -> None:
    """Без настроек SMTP не ходим в сеть вовсе — иначе локальная разработка ждёт таймаут зря."""
    monkeypatch.setattr(email_sender, "_smtp_configured", lambda: False)

    def must_not_run(*args, **kwargs):
        raise AssertionError("SMTP не настроен — соединение открывать нельзя")

    monkeypatch.setattr(email_sender, "_send_sync", must_not_run)

    started = time.monotonic()
    assert await email_sender.send_certificate_pdf_email("x@example.com", b"pdf") is False
    assert time.monotonic() - started < 1


@pytest.mark.asyncio
async def test_the_deadline_leaves_room_for_the_socket_timeout() -> None:
    """
    Бюджеты обязаны быть согласованы: сокет должен успеть сработать сам и дать осмысленную
    ошибку в лог. Если потолок окажется меньше сокетного, в логах останется только TimeoutError
    без указания, на какой фазе SMTP всё встало.
    """
    s = Settings()
    assert s.smtp_timeout_sec > 0
    assert s.smtp_inline_deadline_sec > s.smtp_timeout_sec
