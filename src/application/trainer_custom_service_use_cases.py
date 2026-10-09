"""
Тренер вписывает услугу, которой нет в нашем списке.

До этого список услуг был закрытым (миграция 0028: семь позиций, все про лёд),
и специалист смежной дисциплины физически не мог описать, что он делает. Это
чинится не расширением списка — угадывать дисциплины наперёд мы не умеем, — а
правом вписать своё.

Строка ложится в ту же таблицу ``services``, поэтому ``trainer_services``,
фильтры расписания и абонементы работают с ней без единой правки. Отличие одно:
``is_public=false`` держит её вне общего фильтра каталога, пока админ не решит,
что формулировка годится всем. Тот же приём, что у ``arenas.is_confirmed``.

Дедуп здесь важнее, чем кажется: без него «ОФП», «офп» и «ОФП/СФП» станут тремя
разными услугами, и фильтр каталога развалится на синонимы за месяц.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SERVICE_NAME_MAX_LEN = 128
#: Потолок на тренера. Не про место в базе — про то, что анкета с двадцатью
#: услугами не сообщает клиенту ничего. Упирается — это разговор с поддержкой.
MAX_CUSTOM_SERVICES_PER_TRAINER = 5


class CustomServiceError(ValueError):
    """Название пустое, слишком длинное или тренер упёрся в лимит."""


def normalize_service_name(raw: Any) -> str:
    """Схлопнуть пробелы и обрезать края; регистр НЕ трогаем.

    Регистр оставляем как ввёл тренер: «ОФП» и «Хатха-йога» одинаково законны,
    а автоматический Title Case ломает аббревиатуры. Для сравнения есть
    ``_dedupe_key``.
    """
    value = re.sub(r"\s+", " ", str(raw or "").strip())
    if not value:
        raise CustomServiceError("Напишите название услуги.")
    if len(value) > SERVICE_NAME_MAX_LEN:
        raise CustomServiceError(f"Название — не длиннее {SERVICE_NAME_MAX_LEN} символов.")
    if not re.search(r"\w", value, flags=re.UNICODE):
        raise CustomServiceError("Название должно содержать буквы.")
    return value


def _dedupe_key(name: str) -> str:
    """Ключ сравнения: регистр, пунктуация и пробелы не считаются различием.

    «ОФП/СФП», «ОФП СФП» и «офп/сфп» — одна услуга. Ё→е, потому что половина
    пишет «Хореография», а половина — через «ё» в других словах.
    """
    s = name.casefold().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


async def add_trainer_custom_service(
    session: AsyncSession,
    trainer_id: int,
    raw_name: str,
    *,
    is_online: bool = False,
) -> dict[str, Any]:
    """Привязать к тренеру услугу с этим названием, создав её при необходимости.

    Возвращает ``{"service_id": int, "name": str, "created": bool, "is_public": bool,
    "is_online": bool, "allows_online": bool}``.

    Если название совпадает с уже существующей услугой (нашей общей или ранее
    созданной кем-то), новую строку не плодим — привязываем существующую. Тренер
    видит ровно то, что написал, и при этом попадает в общий фильтр каталога,
    если такая услуга там уже есть. ``is_online`` — формат оффера этого тренера.
    """
    name = normalize_service_name(raw_name)
    key = _dedupe_key(name)
    online = bool(is_online)

    # Сравниваем в Python, а не в SQL: таблица услуг — десятки строк, а
    # воспроизводить ``_dedupe_key`` регэкспами PostgreSQL (с юникодными
    # классами и ё→е) значит держать две реализации одного правила.
    candidates = (
        await session.execute(
            text(
                """
                SELECT id, name, is_public, created_by_trainer_id
                FROM services
                WHERE is_public OR created_by_trainer_id = :tid
                ORDER BY is_public DESC, id
                """
            ),
            {"tid": trainer_id},
        )
    ).fetchall()
    existing = next((row for row in candidates if _dedupe_key(str(row[1])) == key), None)

    if existing is not None:
        service_id, service_name, is_public = int(existing[0]), existing[1], bool(existing[2])
        created = False
        # Совпадение с услугой из нашего списка — это не «своя» услуга. Онлайн у неё
        # закрыт, даже если тренер отметил его в форме «моей услуги нет в списке».
        allows_online = existing[3] is not None
        if not allows_online:
            online = False
    else:
        owned = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM services WHERE created_by_trainer_id = :tid"
                ),
                {"tid": trainer_id},
            )
        ).scalar_one()
        if int(owned or 0) >= MAX_CUSTOM_SERVICES_PER_TRAINER:
            raise CustomServiceError(
                f"Можно добавить не больше {MAX_CUSTOM_SERVICES_PER_TRAINER} своих услуг. "
                "Напишите в поддержку, если нужно больше."
            )
        # sort_order в конец общего списка: своя услуга не должна оттеснять
        # наши позиции в пикере у тех, кто её потом увидит на модерации.
        service_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO services (name, sort_order, is_public, created_by_trainer_id)
                    VALUES (
                        :name,
                        COALESCE((SELECT MAX(sort_order) FROM services), 0) + 1,
                        false,
                        :tid
                    )
                    RETURNING id
                    """
                ),
                {"name": name, "tid": trainer_id},
            )
        ).scalar_one()
        service_name, is_public, created = name, False, True
        allows_online = True

    from src.application.trainer_use_cases import (
        ensure_trainer_service_format_changes_allowed,
        sync_trainer_online_enabled_from_services,
    )

    try:
        await ensure_trainer_service_format_changes_allowed(
            session, trainer_id, {int(service_id): online}
        )
    except ValueError as exc:
        raise CustomServiceError(str(exc)) from exc
    await session.execute(
        text(
            """
            INSERT INTO trainer_services (trainer_id, service_id, is_online)
            VALUES (:tid, :sid, :is_online)
            ON CONFLICT (trainer_id, service_id) DO UPDATE
            SET is_online = EXCLUDED.is_online
            """
        ),
        {"tid": trainer_id, "sid": service_id, "is_online": online},
    )

    await sync_trainer_online_enabled_from_services(session, trainer_id)
    await session.commit()

    if created:
        from src.application.admin_custom_service_notify import (
            notify_admins_new_custom_service,
        )

        try:
            await notify_admins_new_custom_service(
                service_id=int(service_id),
                name=service_name,
                trainer_id=trainer_id,
                is_online=online,
            )
        except Exception:  # noqa: BLE001
            # Тренер уже работает с услугой — уведомление админу не повод ронять запрос.
            logger.exception("notify admins after custom service create failed id=%s", service_id)

    return {
        "service_id": int(service_id),
        "name": service_name,
        "created": created,
        "is_public": is_public,
        "is_online": online,
        "allows_online": allows_online,
    }
