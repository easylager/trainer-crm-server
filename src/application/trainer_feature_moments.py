"""
TASK-030: «фича в нужный момент» — карточки хаба, которые называют ситуацию,
уже сложившуюся у тренера в данных, и показывают, чем продукт её закрывает.

Ни одна из существующих подсказок (`trainer_next_step.py`, ритм-инбокс в
`trainer_hub_action_inbox.py`) не упоминает абонементы, группы, статистику
и постоянных клиентов. Этот модуль — их источник, по тому же принципу, что и
`trainer_next_step.py`: чистая функция «факты → максимум одна карточка», весь
копирайт живёт здесь, а не в JS. Правила проверяются в фиксированном приоритете,
первое совпадение выигрывает — двух обучающих карточек на экране не бывает.

Инвариант: нет ситуации в данных тренера — карточки нет.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Порядок = приоритет правил при одновременном совпадении нескольких (первое выигрывает).
ITEM_RECURRING_CLIENT = "feature_moment_recurring_client"
ITEM_PASS = "feature_moment_pass"
ITEM_GROUPS = "feature_moment_groups"
ITEM_STATS = "feature_moment_stats"
ITEM_CERTIFICATES = "feature_moment_certificates"
# Перенесено из trainer_hub_action_inbox.py (DEC-004 задачи) — то же правило того же
# класса, тот же id, тот же копирайт: только источник истины меняется.
ITEM_CLIENT_NOTES = "client_notes"

_RECURRING_CLIENT_MIN_COUNT = 3
_RECURRING_CLIENT_WINDOW_DAYS = 30
_PASS_MIN_COMPLETED = 5
_GROUP_MIN_CLIENTS_PER_SLOT = 2
_GROUP_MIN_OCCURRENCES = 2  # EDGE-004: не срабатывать на разовом совпадении в слоте
_STATS_MIN_COMPLETED = 3
_STATS_MIN_DAYS_SINCE_FIRST_COMPLETED = 7

_WEEKDAY_DATIVE_PLURAL_RU: dict[int, str] = {
    0: "понедельникам",
    1: "вторникам",
    2: "средам",
    3: "четвергам",
    4: "пятницам",
    5: "субботам",
    6: "воскресеньям",
}

_ORDINAL_RU: dict[int, str] = {
    3: "третье",
    4: "четвёртое",
    5: "пятое",
    6: "шестое",
    7: "седьмое",
    8: "восьмое",
    9: "девятое",
    10: "десятое",
}


def _ordinal_ru(n: int) -> str:
    return _ORDINAL_RU.get(n, f"{n}-е")


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return few
    return many


def _client_display_name(first_name: str | None) -> str:
    name = (first_name or "").strip()
    return name or "Клиент"


async def fetch_trainer_feature_moment_facts(
    session: AsyncSession,
    trainer_id: int,
) -> dict[str, Any]:
    """
    Один SQL-запрос на все правила (Comprehension Tips TASK-030) — сборка инбокса не
    должна добавлять запрос на каждое правило. Каждая CTE даёт максимум одну строку;
    финальный SELECT собирает их в одну строку фактов через LEFT JOIN.

    Все правила исключают песочницу (``is_sandbox`` и у брони, и у клиента) и любой
    статус вне ``confirmed``/``completed`` — allow-list, а не deny-list, тем же
    способом, что и ``real_bookings_count`` в ``trainer_onboarding_checklist.py``.
    Это заодно закрывает EDGE-002 (клиент, которого тренер убрал из брони через
    ``trainer_removed``): такая бронь не попадает ни в один allow-list и не может
    привести к тому, что карточка назовёт убранного клиента.
    """
    r = await session.execute(
        text(
            """
            WITH booking_days AS (
                SELECT
                    b.client_id AS client_id,
                    c.first_name AS client_first_name,
                    (EXTRACT(ISODOW FROM s.slot_date)::int - 1) AS day_of_week,
                    s.start_time AS start_time
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                JOIN clients c ON c.id = b.client_id
                WHERE b.trainer_id = :tid
                  AND b.status IN ('confirmed', 'completed')
                  AND NOT b.is_sandbox
                  AND NOT c.is_sandbox
                  AND b.recurring_client_slot_id IS NULL
                  AND s.slot_date >= CURRENT_DATE - INTERVAL '30 days'
            ),
            recurring_candidate AS (
                SELECT
                    bd.client_id AS client_id,
                    MAX(bd.client_first_name) AS client_first_name,
                    bd.day_of_week AS day_of_week,
                    bd.start_time AS start_time,
                    COUNT(*)::int AS occurrences
                FROM booking_days bd
                GROUP BY bd.client_id, bd.day_of_week, bd.start_time
                HAVING COUNT(*) >= :recurring_min
                   AND NOT EXISTS (
                       SELECT 1 FROM recurring_client_slots r
                       WHERE r.trainer_id = :tid
                         AND r.client_id = bd.client_id
                         AND r.day_of_week = bd.day_of_week
                         AND r.start_time = bd.start_time
                         AND r.status = 'active'
                   )
                ORDER BY occurrences DESC, bd.client_id
                LIMIT 1
            ),
            pass_candidate AS (
                SELECT
                    b.client_id AS client_id,
                    MAX(c.first_name) AS client_first_name,
                    COUNT(*)::int AS occurrences
                FROM bookings b
                JOIN clients c ON c.id = b.client_id
                WHERE b.trainer_id = :tid
                  AND b.status = 'completed'
                  AND NOT b.is_sandbox
                  AND NOT c.is_sandbox
                GROUP BY b.client_id
                HAVING COUNT(*) >= :pass_min
                   AND NOT EXISTS (
                       SELECT 1 FROM pass_instances pi
                       JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
                       WHERE tpp.trainer_id = :tid
                         AND pi.client_id = b.client_id
                         AND pi.status = 'active'
                   )
                ORDER BY occurrences DESC, b.client_id
                LIMIT 1
            ),
            group_slots AS (
                SELECT
                    s.id AS slot_id,
                    s.slot_date AS slot_date,
                    (EXTRACT(ISODOW FROM s.slot_date)::int - 1) AS day_of_week,
                    s.start_time AS start_time,
                    COUNT(DISTINCT b.client_id) AS distinct_clients
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                JOIN clients c ON c.id = b.client_id
                WHERE b.trainer_id = :tid
                  AND b.status IN ('confirmed', 'completed')
                  AND NOT b.is_sandbox
                  AND NOT c.is_sandbox
                GROUP BY s.id, s.slot_date, s.start_time
                HAVING COUNT(DISTINCT b.client_id) >= :group_min_clients
            ),
            group_candidate AS (
                SELECT
                    gs.day_of_week AS day_of_week,
                    gs.start_time AS start_time,
                    COUNT(DISTINCT gs.slot_date)::int AS occurrences,
                    MAX(gs.distinct_clients)::int AS clients_n
                FROM group_slots gs
                GROUP BY gs.day_of_week, gs.start_time
                HAVING COUNT(DISTINCT gs.slot_date) >= :group_min_occurrences
                   AND NOT EXISTS (SELECT 1 FROM training_groups WHERE trainer_id = :tid)
                ORDER BY occurrences DESC
                LIMIT 1
            ),
            completed_stats AS (
                SELECT
                    COUNT(*)::int AS completed_n,
                    MIN(s.slot_date) AS first_completed_date
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                JOIN clients c ON c.id = b.client_id
                WHERE b.trainer_id = :tid
                  AND b.status = 'completed'
                  AND NOT b.is_sandbox
                  AND NOT c.is_sandbox
            ),
            stats_candidate AS (
                SELECT completed_n
                FROM completed_stats
                WHERE completed_n >= :stats_min_completed
                  AND first_completed_date <= CURRENT_DATE - INTERVAL '1 day' * :stats_min_days
                  AND NOT EXISTS (
                      SELECT 1 FROM trainer_feature_first_use
                      WHERE trainer_id = :tid AND feature = 'stats_opened'
                  )
            ),
            certificate_candidate AS (
                SELECT true AS has_moment
                WHERE EXISTS (
                    SELECT 1 FROM pass_instances pi
                    JOIN trainer_pass_products tpp ON tpp.id = pi.pass_product_id
                    JOIN clients c ON c.id = pi.client_id
                    WHERE tpp.trainer_id = :tid
                      AND NOT c.is_sandbox
                )
                AND NOT EXISTS (
                    SELECT 1 FROM trainer_certificate_products WHERE trainer_id = :tid
                )
            )
            SELECT
                rc.client_id, rc.client_first_name, rc.day_of_week, rc.start_time, rc.occurrences,
                pc.client_id, pc.client_first_name, pc.occurrences,
                gc.day_of_week, gc.start_time, gc.clients_n,
                sc.completed_n,
                cc.has_moment
            FROM (SELECT 1 AS _one) _dummy
            LEFT JOIN recurring_candidate rc ON true
            LEFT JOIN pass_candidate pc ON true
            LEFT JOIN group_candidate gc ON true
            LEFT JOIN stats_candidate sc ON true
            LEFT JOIN certificate_candidate cc ON true
            """
        ),
        {
            "tid": trainer_id,
            "recurring_min": _RECURRING_CLIENT_MIN_COUNT,
            "pass_min": _PASS_MIN_COMPLETED,
            "group_min_clients": _GROUP_MIN_CLIENTS_PER_SLOT,
            "group_min_occurrences": _GROUP_MIN_OCCURRENCES,
            "stats_min_completed": _STATS_MIN_COMPLETED,
            "stats_min_days": _STATS_MIN_DAYS_SINCE_FIRST_COMPLETED,
        },
    )
    row = r.fetchone()
    facts: dict[str, Any] = {
        "recurring_client": None,
        "pass": None,
        "groups": None,
        "stats": None,
        "certificates": None,
    }
    if not row:
        return facts
    if row[0] is not None:
        facts["recurring_client"] = {
            "client_id": int(row[0]),
            "client_name": row[1],
            "day_of_week": int(row[2]),
            "start_time": row[3],
            "count": int(row[4]),
        }
    if row[5] is not None:
        facts["pass"] = {
            "client_id": int(row[5]),
            "client_name": row[6],
            "count": int(row[7]),
        }
    if row[8] is not None:
        facts["groups"] = {
            "day_of_week": int(row[8]),
            "start_time": row[9],
            "clients_n": int(row[10]),
        }
    if row[11] is not None:
        facts["stats"] = {"completed_n": int(row[11])}
    if row[12]:
        facts["certificates"] = {"has_moment": True}
    return facts


def _recurring_client_card(fact: dict[str, Any]) -> dict[str, Any]:
    name = _client_display_name(fact.get("client_name"))
    n = int(fact["count"])
    weekday = _WEEKDAY_DATIVE_PLURAL_RU.get(int(fact["day_of_week"]), "")
    start_time = fact.get("start_time")
    time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time or "")
    return {
        "item_id": ITEM_RECURRING_CLIENT,
        "title": f"У {name} обозначился постоянный ритм",
        "subtitle": (
            f"{name} — {_ordinal_ru(n)} занятие подряд по {weekday} в {time_str}. "
            "Заведите постоянного клиента — слоты будут появляться сами, без ручного повтора."
        ),
        "primary_label": "Открыть клиента",
        "primary_action": "trainer_clients",
    }


def _pass_card(fact: dict[str, Any]) -> dict[str, Any]:
    name = _client_display_name(fact.get("client_name"))
    n = int(fact["count"])
    word = _plural_ru(n, "занятие", "занятия", "занятий")
    return {
        "item_id": ITEM_PASS,
        "title": f"{name}: пора предложить абонемент",
        "subtitle": (
            f"{n} {word} подряд без абонемента — с ним занятия списывались бы сами, "
            "а не считались вручную каждый раз."
        ),
        "primary_label": "Оформить абонемент",
        "primary_action": "trainer_pass_products",
    }


def _groups_card(fact: dict[str, Any]) -> dict[str, Any]:
    weekday = _WEEKDAY_DATIVE_PLURAL_RU.get(int(fact["day_of_week"]), "")
    start_time = fact.get("start_time")
    time_str = start_time.strftime("%H:%M") if hasattr(start_time, "strftime") else str(start_time or "")
    n = int(fact.get("clients_n") or 2)
    word = _plural_ru(n, "клиент", "клиента", "клиентов")
    return {
        "item_id": ITEM_GROUPS,
        "title": "Похоже, у вас сложилась группа",
        "subtitle": (
            f"По {weekday} в {time_str} на одно время записываются {n} {word} подряд. "
            "Заведите группу — записываться и оплачивать будет проще, чем по одному."
        ),
        "primary_label": "Группы",
        "primary_action": "trainer_groups",
    }


def _stats_card(fact: dict[str, Any]) -> dict[str, Any]:
    n = int(fact.get("completed_n") or _STATS_MIN_COMPLETED)
    word = _plural_ru(n, "занятие", "занятия", "занятий")
    return {
        "item_id": ITEM_STATS,
        "title": "Первая неделя закрыта — есть что посмотреть",
        "subtitle": (
            f"{n} {word} уже прошло. В разделе статистики видно динамику по клиентам и доходу."
        ),
        "primary_label": "Статистика",
        "primary_action": "trainer_stats",
    }


def _certificates_card(_fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": ITEM_CERTIFICATES,
        "title": "Абонементы уже работают — сертификаты тоже готовы",
        "subtitle": (
            "Подарочный сертификат — способ получить нового клиента от того, кто дарит, "
            "а не ищет тренера сам."
        ),
        "primary_label": "Сертификаты",
        "primary_action": "trainer_certificates",
    }


def _client_notes_card(_fact: dict[str, Any]) -> dict[str, Any]:
    """Перенесено из `_build_hub_rhythm_inbox_candidates` дословно (DEC-004 задачи) —
    тот же текст в том же поле (``title``, без ``subtitle``), чтобы рендер не поменялся."""
    return {
        "item_id": ITEM_CLIENT_NOTES,
        "title": (
            "После завершённой записи можно кратко зафиксировать заметки в карточке клиента — "
            "так проще вести следующие занятия."
        ),
        "subtitle": "",
        "primary_label": "Профиль клиента",
        "primary_action": "client_notes",
    }


def resolve_trainer_feature_moment(
    checklist: dict[str, Any] | None,
    facts: dict[str, Any] | None,
    *,
    dismissed_ids: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """
    Единственная обучающая карточка для хаба, или ``None`` — «нет ситуации, молчим».

    Гейты повторяют ``resolve_trainer_next_step``: тренер центра (расписание ведёт
    администратор) и тренер без активной подписки (Lead Mode) обучающих карточек
    не получают — предлагать функцию, которая выключена, обман (AC-007, EDGE-001).
    """
    if not checklist:
        return None
    if not checklist.get("schedule_unlocked", True):
        return None
    if checklist.get("studio_access_mode") == "admin_only":
        return None
    if checklist.get("has_crm_subscription_access") is False:
        return None

    f = facts or {}

    recurring = f.get("recurring_client")
    if recurring and ITEM_RECURRING_CLIENT not in dismissed_ids:
        return _recurring_client_card(recurring)

    pass_fact = f.get("pass")
    if pass_fact and ITEM_PASS not in dismissed_ids:
        return _pass_card(pass_fact)

    groups_fact = f.get("groups")
    if groups_fact and ITEM_GROUPS not in dismissed_ids:
        return _groups_card(groups_fact)

    stats_fact = f.get("stats")
    if stats_fact and ITEM_STATS not in dismissed_ids:
        return _stats_card(stats_fact)

    cert_fact = f.get("certificates")
    if cert_fact and ITEM_CERTIFICATES not in dismissed_ids:
        return _certificates_card(cert_fact)

    # Перенесено из ритм-инбокса (DEC-004): то же условие, что раньше читалось прямо
    # в `_build_hub_rhythm_inbox_candidates` — есть хотя бы одна завершённая реальная запись.
    if checklist.get("has_completed_booking") and ITEM_CLIENT_NOTES not in dismissed_ids:
        return _client_notes_card({})

    return None


__all__ = [
    "ITEM_RECURRING_CLIENT",
    "ITEM_PASS",
    "ITEM_GROUPS",
    "ITEM_STATS",
    "ITEM_CERTIFICATES",
    "ITEM_CLIENT_NOTES",
    "fetch_trainer_feature_moment_facts",
    "resolve_trainer_feature_moment",
]
