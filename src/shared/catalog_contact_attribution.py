"""Copy for catalog → Telegram DM attribution (TASK-180-adjacent product polish).

Keep in sync with ``static/webapp/catalog-contact-attribution.js``.
"""

CATALOG_TELEGRAM_DM_PREFILL = (
    "Здравствуйте! Пишу из каталога Glide. "
    "Хочу заниматься — подскажите, как удобнее записаться?"
)

CATALOG_CONTACT_HINT = (
    "Откроется чат в Telegram — в поле сообщения подставим короткий текст про Glide, "
    "его можно отредактировать перед отправкой."
)

__all__ = ["CATALOG_CONTACT_HINT", "CATALOG_TELEGRAM_DM_PREFILL"]
