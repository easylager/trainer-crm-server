"""
Момент первого успеха после первой записи (TASK-096 S4, AC-004).

Экран успеха сегодня одинаков для первой записи и для пятидесятой. Но человек,
записавшийся впервые, не знает главного: сработало ли вообще, кто теперь ответит и
что произойдёт дальше. Именно эта неизвестность — а не отсутствие анимации — портит
первый успех. Поэтому «момент» здесь состоит из честных фактов о ближайшем будущем,
а не из украшений.

Всё, что отсюда уходит на экран, выводится из базы:
  * «первая» — счёт записей этого профиля, а не догадка;
  * план напоминаний — тот самый, что реально запланирован
    (``compute_booking_reminder_schedule``), а не обещание вообще.

Ничего не выдумывается (AC-005): если напоминаний по этой записи не будет — поздняя
запись, до слота нет окна — строки про напоминания просто нет, вместо неё не
появляется утешительная неправда.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import compute_booking_reminder_schedule

# Подписи для клиента, а не для тренера. У тренера в кабинете стоит точное
# «09.09 18:00 (за 24 ч)» — ему нужно время отправки. Клиенту нужен смысл.
_REMINDER_LABELS_RU: dict[str, str] = {
    "before_24h": "за сутки",
    "before_2h": "за два часа",
    "before_evening_prior": "накануне вечером",
}


def format_reminder_plan_for_client(plan: list[tuple[str, datetime]]) -> str:
    """
    ``[("before_24h", …), ("before_2h", …)]`` → ``"за сутки и за два часа до начала"``.

    Пустой план → пустая строка. Строка читается вслух как фраза, поэтому последний
    разделитель — «и», а не запятая.
    """
    labels = [_REMINDER_LABELS_RU[k] for k, _ in plan if k in _REMINDER_LABELS_RU]
    if not labels:
        return ""
    if len(labels) == 1:
        joined = labels[0]
    else:
        joined = ", ".join(labels[:-1]) + " и " + labels[-1]
    return f"{joined} до начала"


async def count_client_bookings(session: AsyncSession, client_id: int) -> int:
    """
    Сколько записей всего у этого профиля, включая отменённые.

    Отменённые считаются намеренно: «первая запись» — это про первый раз, когда
    человек прошёл путь до конца, а не про первую действующую бронь. Иначе клиент,
    отменивший дебютную запись, получил бы «ваша первая запись» дважды.
    """
    row = await session.execute(
        text("SELECT count(*) FROM bookings WHERE client_id = :cid"),
        {"cid": int(client_id)},
    )
    return int(row.scalar_one() or 0)


async def build_first_booking_success(
    session: AsyncSession,
    *,
    client_id: int,
    slot_date: date | None,
    start_time: time | None,
) -> dict[str, Any]:
    """
    Поля момента первого успеха для ответа на создание записи.

    Возвращает ``is_first_booking`` всегда и ``reminder_plan`` только когда
    напоминания действительно запланированы. Ошибка расчёта не роняет запись:
    человек уже записан, и подсказка на экране не стоит 500-й ошибки.
    """
    out: dict[str, Any] = {"is_first_booking": False}
    try:
        out["is_first_booking"] = await count_client_bookings(session, client_id) == 1
    except Exception:  # noqa: BLE001 — украшение экрана не важнее самой записи
        return out

    if not out["is_first_booking"] or slot_date is None or start_time is None:
        return out

    try:
        plan = compute_booking_reminder_schedule(
            anchor_local=datetime.now(timezone.utc),
            slot_date=slot_date,
            start_time=start_time,
        )
    except Exception:  # noqa: BLE001
        return out

    human = format_reminder_plan_for_client(plan)
    if human:
        out["reminder_plan"] = human
    return out
