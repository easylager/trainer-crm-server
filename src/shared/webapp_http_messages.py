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

MINIAPP_ADMIN_NOT_CONFIGURED_DETAIL_RU = "Административное мини-приложение временно недоступно. Попробуйте позже."
MINIAPP_ADMIN_PLATFORM_NOT_SUPPORTED_DETAIL_RU = "Административное мини-приложение доступно только в Telegram."
MINIAPP_NOT_ADMIN_DETAIL_RU = "У вас нет доступа к этому разделу."
MINIAPP_PLATFORM_NOT_SUPPORTED_DETAIL_RU = "Эта платформа мини-приложения пока не поддерживается."
MINIAPP_VK_NOT_CONFIGURED_DETAIL_RU = "Мини-приложение временно недоступно. Попробуйте позже."
MINIAPP_TRAINER_NOT_CONFIGURED_DETAIL_RU = "Мини-приложение тренера временно недоступно. Попробуйте позже."
MINIAPP_CLIENT_NOT_CONFIGURED_DETAIL_RU = "Мини-приложение клиента временно недоступно. Попробуйте позже."

__all__ = [
    "MINIAPP_ADMIN_NOT_CONFIGURED_DETAIL_RU",
    "MINIAPP_ADMIN_PLATFORM_NOT_SUPPORTED_DETAIL_RU",
    "MINIAPP_CLIENT_NOT_CONFIGURED_DETAIL_RU",
    "MINIAPP_NOT_ADMIN_DETAIL_RU",
    "MINIAPP_PLATFORM_NOT_SUPPORTED_DETAIL_RU",
    "MINIAPP_TRAINER_NOT_CONFIGURED_DETAIL_RU",
    "MINIAPP_VK_NOT_CONFIGURED_DETAIL_RU",
    "TRAINER_WEBAPP_FORBIDDEN_DETAIL",
    "WEBAPP_DETAIL_SUBSCRIPTION_ANALYTICS_REQUIRED",
    "WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED",
    "WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED",
]
