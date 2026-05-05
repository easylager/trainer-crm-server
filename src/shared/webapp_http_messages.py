"""Russian HTTP `detail` strings for trainer Web App APIs (user-visible, not dev diagnostics)."""

# Was English «Trainer not linked or not active» — misleading when Telegram is linked but status≠active (catalog moderation).
TRAINER_WEBAPP_FORBIDDEN_DETAIL = (
    "Действие недоступно: профиль тренера не активирован или Telegram не привязан к аккаунту. "
    "Если онбординг уже пройден — карточка может быть на проверке и ещё не опубликована в каталоге."
)

# Lead Mode / lapsed subscription: CRM writes (slots, trainer-side bookings, template).
WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED = (
    "Сейчас нет активной подписки с модулем CRM: создавать и менять слоты и вести записи через "
    "систему можно после продления. Профиль в каталоге остаётся — откройте «Подписка» в Обзоре."
)

WEBAPP_DETAIL_SUBSCRIPTION_ANALYTICS_REQUIRED = (
    "Раздел статистики доступен с тарифом, где подключён модуль «Аналитика». "
    "Оформите подходящий тариф в «Подписке»."
)

WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED = (
    "Групповые занятия доступны с модулем «Группы» в подписке. Оформите тариф в «Подписке»."
)

__all__ = [
    "TRAINER_WEBAPP_FORBIDDEN_DETAIL",
    "WEBAPP_DETAIL_SUBSCRIPTION_ANALYTICS_REQUIRED",
    "WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED",
    "WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED",
]
