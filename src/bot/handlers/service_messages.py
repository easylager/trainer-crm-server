"""Служебные сообщения Telegram: бот их молча пропускает.

Это не ввод человека, а отметки самого Telegram: «вы разрешили боту писать»
(``write_access_allowed`` после requestWriteAccess в Mini App), закреп, таймер
автоудаления, фон чата. Раньше они доходили до общего ``fallback`` и получали
«Нажмите кнопку Главная…», а в шагах записи съедались как пустой ответ.
Роутер подключается первым — раньше любых обработчиков состояний.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.types import Message

SERVICE_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        ContentType.WRITE_ACCESS_ALLOWED,
        ContentType.PINNED_MESSAGE,
        ContentType.MESSAGE_AUTO_DELETE_TIMER_CHANGED,
        ContentType.CHAT_BACKGROUND_SET,
        ContentType.USERS_SHARED,
        ContentType.CHAT_SHARED,
        ContentType.PROXIMITY_ALERT_TRIGGERED,
        ContentType.BOOST_ADDED,
        ContentType.GIFT,
        ContentType.UNIQUE_GIFT,
        ContentType.REFUNDED_PAYMENT,
        ContentType.CHECKLIST_TASKS_DONE,
        ContentType.CHECKLIST_TASKS_ADDED,
    }
)


def is_service_message(message: Message) -> bool:
    return message.content_type in SERVICE_CONTENT_TYPES


async def ignore_service_message(message: Message) -> None:
    return None


def build_service_messages_router() -> Router:
    """Свой экземпляр на каждый Dispatcher: aiogram не даёт подключить один роутер дважды."""
    router = Router(name="service_messages")
    router.message.register(ignore_service_message, F.content_type.in_(SERVICE_CONTENT_TYPES))
    return router
