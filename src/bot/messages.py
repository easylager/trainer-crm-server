"""
All user-facing bot messages. Clear names; no hardcoding in handlers.
Prefixes: client bot vs trainer bot.
"""

# --- Client bot ---
CLIENT_START_WELCOME = "Привет! Здесь ты можешь найти тренера и записаться на занятие. Нажми «Каталог тренеров» ниже."
CLIENT_FALLBACK = "Отправь /start или нажми «Каталог тренеров»."
CLIENT_CATALOG_LOADING = "Загружаю каталог тренеров..."
CLIENT_CATALOG_HEADER = "Вот наши тренеры:"
CLIENT_CATALOG_EMPTY = "Пока нет активных тренеров. Загляни позже."
CLIENT_TRAINER_CARD = (
    "<b>{name}</b>\n"
    "Возраст: {age} лет\n"
    "Опыт: {experience}\n"
    "{description}"
)
CLIENT_TRAINER_CARD_NO_EXPERIENCE = "Опыт: не указан"

# --- Trainer bot (entry only via paid link from site) ---
TRAINER_START_WELCOME = "Привет! Ты зашёл как тренер. Управление расписанием и записями — в разработке."
TRAINER_ONLY_VIA_SITE = "Этот бот только для тренеров. Подключение по ссылке с сайта после регистрации и оплаты."
TRAINER_LINK_SUCCESS = "Твой аккаунт тренера привязан к этому Telegram. Можешь пользоваться ботом."
TRAINER_LINK_INVALID = "Ссылка недействительна или уже использована. Получи новую на сайте после оплаты."
