"""
Хаб тренера: одна карточка «следующий шаг» вместо чеклиста.

Почему одна, а не список. Чеклист из трёх пунктов с блокировками — это карта территории,
которую тренер не просил. Он показывает, сколько ещё не сделано, требует прочитать три
заголовка и выбрать, и в момент максимальной неуверенности предлагает три равнозначные
кнопки. Одна карточка показывает ровно то, что имеет смысл сделать прямо сейчас, и исчезает,
когда делать нечего — а «нечего» здесь нормальное и частое состояние.

Функция чистая: словарь фактов на входе, карточка на выходе. Весь копирайт онбординга живёт
здесь, а не размазан по 200 строкам ветвлений в JS.
"""
from __future__ import annotations

from typing import Any

# Сколько реальных занятий должно пройти по личной ссылке, прежде чем предлагать каталог.
# Смысл порога: каталог — награда за работающую практику, а не задание на старте. Пока у
# тренера нет своего потока, обещание «вас найдут новые ученики» продукт выполнить не может.
CATALOG_INVITE_MIN_BOOKINGS = 5

# Действия, которые понимает хаб. Держим список коротким намеренно.
ACTION_OPEN_ONBOARDING = "open_onboarding"
ACTION_SHARE_LINK = "share_link"
ACTION_OPEN_PROFILE = "open_profile"
ACTION_ENABLE_CATALOG = "enable_catalog"
# Opt-in уже дан — открыть ту же карусель catalog (без второго «флоу»).
ACTION_OPEN_CATALOG_PROFILE = "open_catalog_profile"
ACTION_DISMISS = "dismiss"

# Короткие имена полей для карточки. Ключи = submission missing_fields.
# Фамилия для каталога необязательна → full_name в тексте = «имя».
_CATALOG_CARD_FIELD_WORDS: dict[str, str] = {
    "full_name": "имя",
    "phone": "телефон",
    "photo": "фото",
    "city": "город",
    "arenas": "площадка",
    "services": "услуга",
    "session_duration_minutes": "длительность занятия",
    "min_hours_before_booking": "окно записи",
}


def _catalog_card_requirements(missing_fields: list[str] | None) -> str:
    """«телефон, город и площадка» — то, чего действительно не хватает, или '' когда всё есть."""
    words = [
        _CATALOG_CARD_FIELD_WORDS[k]
        for k in (missing_fields or [])
        if k in _CATALOG_CARD_FIELD_WORDS
    ]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " и " + words[-1]


STEP_SETUP_WEEK = "setup_week"
STEP_REFRESH_WEEK = "refresh_week"
STEP_SHARE_LINK = "share_link"
STEP_SET_ARENA = "set_arena"
STEP_CATALOG_INVITE = "catalog_invite"


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not (10 <= n % 100 < 20):
        return few
    return many


def resolve_trainer_next_step(
    checklist: dict[str, Any] | None,
    *,
    catalog_invite_dismissed: bool = False,
) -> dict[str, Any] | None:
    """
    Единственная карточка для хаба, или ``None``, когда подсказывать нечего.

    Порядок проверок = порядок срочности. Первое совпадение выигрывает: две карточки на
    экране — это уже чеклист.
    """
    if not checklist:
        return None
    if not checklist.get("schedule_unlocked", True):
        return None  # деактивированный аккаунт: подсказки неуместны
    if checklist.get("studio_access_mode") == "admin_only":
        return None  # тренер центра: расписание ведёт администратор

    has_week = int(checklist.get("weekly_template_count") or 0) > 0
    has_slots = bool(checklist.get("has_future_slots"))
    # has_real_booking (not has_any_booking): a sandbox demo or an instantly-voided booking
    # must not hide the «отправьте ссылку ученику» card — see TASK-027.
    has_booking = bool(checklist.get("has_real_booking"))
    real_bookings = int(checklist.get("real_bookings_count") or 0)
    catalog_opted_in = bool(checklist.get("is_catalog_visible"))
    catalog_missing = list(checklist.get("catalog_missing_fields") or [])
    catalog_need = _catalog_card_requirements(catalog_missing)

    # 1. Недели нет — работать нечем. Это единственный по-настоящему обязательный шаг.
    if not has_week and not has_slots:
        return {
            "key": STEP_SETUP_WEEK,
            "title": "Настройте расписание",
            # «Без анкеты» не пишем: отрицание всё равно называет анкету и подсказывает,
            # что где-то она есть. Говорим про длительность и результат.
            "body": "Две минуты, ничего заполнять не нужно. Дальше ученик выберет время сам.",
            "cta": {"label": "Начать", "action": ACTION_OPEN_ONBOARDING},
            "secondary": None,
        }

    # 2. Неделя настроена, но впереди пусто: слоты кончились и новых не сгенерировалось.
    #    Отправлять ссылку в этом состоянии — значит показать ученику пустой экран.
    #    Обещание ссылки и реальность расписания обязаны совпадать, иначе ломается доверие
    #    ровно к тому каналу, который мы построили.
    if not has_slots:
        return {
            "key": STEP_REFRESH_WEEK,
            "title": "Свободных окон не осталось",
            "body": "Ученик откроет ссылку и не увидит времени. Откройте расписание на ближайшие недели.",
            "cta": {"label": "Обновить расписание", "action": ACTION_OPEN_ONBOARDING},
            "secondary": None,
        }

    # 3. Расписание есть, но никто ни разу не записывался. Одна кнопка, одна задача.
    if not has_booking:
        return {
            "key": STEP_SHARE_LINK,
            "title": "Отправьте ссылку одному ученику",
            "body": (
                "Тому, кто и так собирался к вам на этой неделе. "
                "Он выберет время сам — вам придёт уведомление."
            ),
            "cta": {"label": "Отправить ученику", "action": ACTION_SHARE_LINK},
            "secondary": None,
        }

    # Площадку и необязательные поля профиля (цены, «что не входит») в хаб не выносим:
    # после первой записи кабинет уже работает, а мягкие пуши D+1/D+8/D+21 ведут в профиль
    # без отдельного блока на главном экране.

    # После первой записи карточку «отправьте ссылку» больше не держим.
    # Повторять ссылку — дело хинтов, не отдельного блока на хабе.

    # 5. Одна карточка каталога → одна карусель ``task=catalog`` (телефон + имя в рельсе).
    #    Не opted-in: согласие + карусель. Уже opted-in, но дыры: та же карусель без второго флоу.
    if (
        real_bookings >= CATALOG_INVITE_MIN_BOOKINGS
        and not bool(checklist.get("is_active"))
        and not (catalog_opted_in and not catalog_need)
        and not (catalog_invite_dismissed and not catalog_opted_in)
    ):
        word = _plural(real_bookings, "занятие", "занятия", "занятий")
        if catalog_opted_in and catalog_need:
            return {
                "key": STEP_CATALOG_INVITE,
                "title": "Вас уже записывают",
                "body": (
                    f"{real_bookings} {word} по вашей ссылке. "
                    f"Для карточки в каталоге не хватает: {catalog_need}."
                ),
                "cta": {"label": "Продолжить", "action": ACTION_OPEN_CATALOG_PROFILE},
                "secondary": None,
            }
        if not catalog_opted_in:
            tail = (
                f"Для карточки не хватает: {catalog_need}."
                if catalog_need
                else "Карточка уже готова."
            )
            return {
                "key": STEP_CATALOG_INVITE,
                "title": "Вас уже записывают",
                "body": (
                    f"{real_bookings} {word} по вашей ссылке. "
                    f"Хотите, чтобы вас находили новые ученики? {tail}"
                ),
                "cta": {"label": "Хочу в каталог", "action": ACTION_ENABLE_CATALOG},
                "secondary": {"label": "Не сейчас", "action": ACTION_DISMISS},
            }

    # Подсказывать нечего — и это нормальное состояние работающего кабинета.
    return None
