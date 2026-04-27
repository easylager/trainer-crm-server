"""Russian HTTP `detail` strings for trainer Web App APIs (user-visible, not dev diagnostics)."""

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
    "WEBAPP_DETAIL_SUBSCRIPTION_ANALYTICS_REQUIRED",
    "WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED",
    "WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED",
]
