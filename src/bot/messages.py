"""
All user-facing bot messages. Clear names; no hardcoding in handlers.
Prefixes: client bot vs trainer bot.
"""

# --- Client bot ---
CLIENT_START_WELCOME = "Привет! Здесь ты можешь найти тренера и записаться на занятие. Меню ниже."
CLIENT_FALLBACK = "Отправь /start, чтобы начать."

# --- Trainer bot (entry only via paid link from site) ---
TRAINER_START_WELCOME = "Привет! Ты зашёл как тренер. Управление расписанием и записями — в разработке."
TRAINER_ONLY_VIA_SITE = "Этот бот только для тренеров. Подключение по ссылке с сайта после регистрации и оплаты."
TRAINER_LINK_SUCCESS = "Твой аккаунт тренера привязан к этому Telegram. Можешь пользоваться ботом."
TRAINER_LINK_INVALID = "Ссылка недействительна или уже использована. Получи новую на сайте после оплаты."
