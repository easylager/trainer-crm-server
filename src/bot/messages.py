"""
All user-facing bot messages. Clear names; no hardcoding in handlers.
Prefixes: client bot vs trainer bot.

Voice (UX):
- Client bot: «Вы», нейтрально-дружелюбно; без канцелярита; CTA ведут в меню («Тренеры и запись», «Мои записи»), не в несуществующие команды.
- Trainer bot: «ты», коротко и по делу; пуши: заголовок + суть + что сделать в меню слева.
- Кнопки «назад»/пагинация: префикс ◀️ / ▶️ где уместно; не дублировать десяток эмодзи в одном абзаце.
- Не хардкодить тексты в handlers — только через константы здесь.
"""

from __future__ import annotations

import html

from src.shared.byr_currency_display import BYR_SIGN, format_kopeks_byn_display, format_rubles_byn_display
from src.shared.validation import truncate_text

# --- Client bot ---
CLIENT_START_WELCOME = (
    "👋 Привет! Здесь можно найти тренера и записаться на занятие. "
    "Нажмите кнопку <b>Главная</b> слева от поля ввода — там каталог, записи и заявки. Помощь: /guide"
)
CLIENT_FALLBACK = "Нажмите кнопку <b>Главная</b> слева от поля ввода. Помощь: /guide"

# Bot-mediated relay when trainer ↔ client can't use native Telegram DM
CLIENT_RELAY_REPLY_PROMPT = "Напишите здесь — тренер увидит сообщение сразу."
TRAINER_RELAY_REPLY_PROMPT = "Напиши здесь — отправим клиенту."
TRAINER_BOOKING_RELAY_SELF_DISABLED = "Эта кнопка выключена в настройках сервера."
TRAINER_BOOKING_RELAY_SELF_NOT_SELF_CLIENT = (
    "Кнопка только для записи, где клиент привязан к вашему же Telegram (локальный тест)."
)
RELAY_SESSION_IDLE_CLOSED_HINT = "<b>Переписка через бота закрыта</b> — долго не было сообщений."


def _relay_reply_only_markup(callback_prefix: str, session_id: int):
    """Single «Ответить» inline row; trainer uses ``rly_r``, client bot uses ``rly_ck``."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    sid = int(session_id)
    pfx = (callback_prefix or "").strip().rstrip(":")
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Ответить", callback_data=f"{pfx}:{sid}")]],
    )


def build_trainer_relay_reply_only_keyboard(session_id: int):
    """Re-arm reply mode for trainer (callback rly_r:)."""
    return _relay_reply_only_markup("rly_r", session_id)


def build_client_relay_reply_only_keyboard(session_id: int):
    """Same UX on client bot (callback rly_ck:)."""
    return _relay_reply_only_markup("rly_ck", session_id)


def format_client_relay_from_trainer_html(*, trainer_name: str, body_text: str) -> str:
    safe_name = html.escape((trainer_name or "").strip() or "Тренер")
    escaped_body = html.escape(body_text.strip())
    return f"💬 <b>Сообщение от тренера {safe_name}</b>\n\n{escaped_body}"


def format_trainer_relay_from_client_html(*, client_name: str, body_text: str) -> str:
    safe_name = html.escape((client_name or "").strip() or "Клиент")
    escaped_body = html.escape(body_text.strip())
    return f"💬 <b>Сообщение от клиента {safe_name}</b>\n\n{escaped_body}"

TRAINER_RELAY_SESSION_CLOSED_HINT = (
    "Переписка через бота завершена. Новое сообщение — снова из раздела «Мои клиенты» или записи."
)
CLIENT_RELAY_SESSION_CLOSED_HINT = "Переписка через бота с тренером завершена."

# Client hub Mini App (HTTPS): contextual home + links to catalog, bookings, requests, passes
CLIENT_HOME_OPEN_WEBAPP = (
    "<b>Главная</b> — ближайшие записи, заявки и быстрые переходы: тренеры, записи, отклики, абонементы."
)
CLIENT_BUTTON_HOME_WEBAPP = "Открыть главную"
# Telegram chat menu button (left of input); short label
CLIENT_MENU_BUTTON_HUB = "Главная"
CLIENT_HOME_HTTPS_REQUIRED = (
    "Экран «Главная» доступен при HTTPS (нужен WEBAPP_BASE_URL или API_BASE_URL в продакшене)."
)
CLIENT_CATALOG_LOADING = "Загружаю каталог тренеров..."
CLIENT_CATALOG_HEADER = "Вот наши тренеры:"
CLIENT_CATALOG_EMPTY = "Пока нет активных тренеров. Загляните позже."
CLIENT_CATALOG_PAGINATION_LEAVE_REQUEST = "Не нашли подходящего тренера? Оставьте заявку — мы подберём для вас тренера."
CLIENT_CHOOSE_CITY = "Выберите город:"
CLIENT_CHOOSE_SERVICE = "Выберите услугу:"
CLIENT_TRAINER_CARD = (
    "<b>{name}</b>\n"
    "Рейтинг: {rating}\n"
    "Возраст: {age} лет\n"
    "Опыт: {experience}\n"
    "Занятие: {duration} мин\n"
    "Арены: {arenas}\n"
    "Услуги и цены: {services_prices}\n"
    "{description}"
)
CLIENT_TRAINER_CARD_NO_RATING = "—"
CLIENT_TRAINER_CARD_NO_EXPERIENCE = "Опыт: не указан"
CLIENT_BUTTON_SELECT_TRAINER = "Выбрать"
CLIENT_TRAINER_SELECTED = "Выбран: <b>{name}</b>. Что дальше?"
# Public invite link (t.me/...?start=client_...) — no «another trainer»; service from link.
CLIENT_DEEP_LINK_BOOK_INVITE = (
    "Привет! Тебя пригласил записаться тренер <b>{trainer}</b>.\n\n"
    "Выбранная услуга: <b>{service}</b>.\n\n"
    "Нажми кнопку ниже, чтобы выбрать удобное время."
)
CLIENT_DEEP_LINK_BOOK_INVITE_PICK_SERVICE = (
    "Привет! Тебя пригласил записаться тренер <b>{trainer}</b>.\n\n"
    "Нажми кнопку ниже: сначала выбери услугу, потом удобное время."
)
# Tier < online: no self-booking in catalog — same UX as Mini App can_book=false
CLIENT_TRAINER_SELECTED_NO_SELF_BOOK = (
    "Выбран: <b>{name}</b>.\n\n"
    "У этого тренера нет самозаписи через каталог — свяжитесь напрямую или оставьте заявку."
)
CLIENT_BOOK_NO_ONLINE_TIER = (
    "У выбранного тренера нет онлайн-записи через каталог. "
    "Свяжитесь с тренером напрямую или оставьте заявку в каталоге."
)
CLIENT_BUTTON_BOOK = "Записаться"
# After activating a gift certificate: single CTA to book with the issuing trainer
CLIENT_BUTTON_CERT_TRAINER_BOOK = "Тренер и запись"
CLIENT_BUTTON_BACK_TO_CATALOG = "В каталог"
CLIENT_BUTTON_ANOTHER_TRAINER = "Выбрать другого тренера"
CLIENT_BOOK_CHOOSE_SLOT = "📅 <b>Выберите время</b>\n\nДоступные слоты (эта и следующая неделя):"
CLIENT_BOOK_NO_SLOTS = "У этого тренера пока нет свободных слотов. Загляните позже или выберите другого тренера."
CLIENT_BOOK_NO_TRAINER = "Сначала выберите тренера в каталоге."
# Stale in-memory booking flow (restart, old callback) — do not confuse with «no trainer selected».
CLIENT_BOOK_SESSION_EXPIRED = (
    "Сессия записи устарела или была сброшена. Откройте каталог, снова выберите тренера и нажмите «Записаться»."
)
# When HTTPS Mini App is used, slot list in chat is omitted — clarify where user picks time.
CLIENT_BOOK_WEBAPP_FOOTER = (
    "\n\nВремя занятия выберите в <b>Mini App</b> после нажатия кнопки «Записаться» ниже."
)
CLIENT_MENU_BOOKING_MOVED = (
    "Записаться можно в «Тренеры и запись»: откройте каталог и карточку тренера. "
    "Время и слот выберите в <b>Mini App</b> после нажатия кнопки «Записаться» ниже."
)
CLIENT_MENU_REQUEST_MOVED = "Оставить заявку можно в «Тренеры и запись»: внизу списка тренеров или в карточке тренера."
CLIENT_PROFILE_ENTER_NAME = (
    "Напишите, пожалуйста, <b>Имя</b> (обязательно) и при желании <b>фамилию</b> через пробел — "
    "так вас будут видеть тренеры."
)
CLIENT_PROFILE_USE_TELEGRAM_NAME = "Использовать имя из Telegram: {name}?"
CLIENT_BUTTON_USE_TG_NAME = "Да"
CLIENT_BUTTON_ENTER_MANUAL = "Ввести вручную"
CLIENT_PROFILE_NAME_INVALID = "Укажите хотя бы <b>имя</b> одним словом или имя и фамилию, например: Иван или Иван Петров."
CLIENT_BOOK_ENTER_PHONE = "Введите номер телефона (например +375291234567) или нажмите кнопку ниже, чтобы отправить контакт."
CLIENT_BOOK_ENTER_COMMENT = "Комментарий к записи (необязательно). Напишите текст или нажмите «Пропустить»."
CLIENT_BOOK_SKIP_COMMENT = "Пропустить"
# Single source of truth: after any booking, direct to «Мои записи» (plan §4.1)
CLIENT_MY_RECORDS_CTA = "Детали, адрес и отмена — в <b>«Мои записи»</b> в меню бота."

CLIENT_BOOK_SUCCESS = "✅ Вы оставили запрос на занятие <b>{date}</b> ({day}) {time}, {duration} мин."
CLIENT_BOOK_WHAT_NEXT = "Дождитесь подтверждения от тренера — мы сообщим, когда он ответит."
CLIENT_BOOK_SUCCESS_HINT = CLIENT_MY_RECORDS_CTA
CLIENT_BOOK_BUTTON_BACK = "◀️ Назад"
CLIENT_BOOK_PHONE_INVALID = "Нужен номер телефона. Отправьте текст (например +375291234567) или нажмите «Отправить контакт»."
CLIENT_BOOK_BUTTON_SEND_CONTACT = "📱 Отправить контакт"
CLIENT_BOOK_RECORDED = "Запись оформлена."
CLIENT_BOOK_COMMENT_OR_BUTTON = "Напишите комментарий или нажмите кнопку:"

# Link by phone (trainer added client; user attaches Telegram)
CLIENT_LINK_PHONE_PROMPT = "Введите номер телефона (как указали тренеру при записи):"
CLIENT_LINK_PHONE_NOT_FOUND = "Клиент с таким номером не найден. Запишитесь через тренера — тогда вы появитесь здесь."
CLIENT_LINK_PHONE_ALREADY_LINKED = "Этот номер уже привязан к аккаунту."
CLIENT_LINK_CODE_SENT = "Код для проверки отправлен на ваш номер. Введите код:"
CLIENT_LINK_CODE_DEV = " (для проверки код: <code>{code}</code>)"
CLIENT_LINK_SUCCESS = "Готово! Ваш профиль привязан. Теперь можете записаться к тренеру."
CLIENT_LINK_CODE_WRONG = "Неверный код. Введите код из сообщения."

# Trainer bot: client completed public invite registration form.
TRAINER_CLIENT_REGISTERED_NEW_HTML = (
    "🆕 <b>Новый клиент по твоей ссылке</b>\n\n"
    "{client_label} заполнил(а) короткий профиль и добавлен(а) в раздел «Клиенты»."
)
TRAINER_CLIENT_REGISTERED_LINKED_HTML = (
    "✅ <b>Клиент теперь в боте</b>\n\n"
    "{client_label} заполнил(а) профиль по твоей ссылке. "
    "Telegram привязан к существующей карточке в разделе «Клиенты»."
)
TRAINER_CLIENT_REGISTERED_OPEN_PROFILE_BTN = "Открыть профиль клиента"
TRAINER_CLIENT_FAMILY_MEMBER_HTML = (
    "👥 <b>Семейный доступ</b>\n\n"
    "К карточке {client_label} подключился ещё один аккаунт в Telegram: {member_label}."
)

# Client: errors and hints (what to do next)
CLIENT_ERROR_BOOKING_CLOSED = "Эта запись уже закрыта или недоступна. Выберите другого тренера или время в каталоге."
CLIENT_ERROR_BOOKING_UNAVAILABLE = "Эта запись недоступна. Выберите слот в каталоге или нажмите «Записаться»."
CLIENT_ERROR_NO_CITIES = "Нет доступных городов. Выберите город позже или напишите в поддержку."
CLIENT_ERROR_NO_SERVICES = "Нет доступных услуг. Выберите услугу позже или напишите в поддержку."
CLIENT_ERROR_NO_CITIES_ADMIN = "Нет доступных городов. Обратитесь к администратору."
CLIENT_ERROR_NO_SERVICES_ADMIN = "Нет доступных услуг. Обратитесь к администратору."
CLIENT_ERROR_CHOOSE_CITY_FIRST = "Сначала выберите город в «Тренеры и запись» (меню слева)."
CLIENT_ERROR_REQUEST_NOT_FOUND = "Заявка не найдена. Откройте «Мои заявки» и попробуйте снова."
CLIENT_ERROR_TRY_AGAIN = "Произошла ошибка. Попробуйте ещё раз или введите /guide."
CLIENT_ERROR_TRAINER_NOT_FOUND = "Тренер не найден. Откройте каталог и выберите тренера заново."
CLIENT_ERROR_SERVICE_UNKNOWN_FOR_BOOKING = (
    "Не удалось определить услугу. Выберите услугу в каталоге и попробуйте снова."
)

# Client: /guide (Помощь) — short, scannable; main menu is left of input
CLIENT_GUIDE = (
    "❓ <b>Помощь</b>\n\n"
    "Всё в <b>меню слева</b> от поля ввода.\n\n"
    "• <b>Тренеры и запись</b> — выберите город/услугу/арену, откройте карточку тренера: там слоты, «Записаться» и «Оставить заявку».\n"
    "• <b>Мои заявки</b> — ваши заявки и отклики тренеров.\n"
    "• <b>Мои записи</b> — ближайшие занятия; отмена — в разделе «Мои записи» или напишите тренеру.\n"
    "• <b>Ваша активность</b> — сколько тренировок уже за плечами и серия недель; на <b>Главной</b> при серии показываем короткую плашку — нажмите, чтобы открыть подробности.\n\n"
    "Не нашли ответ? Нажмите «Написать в поддержку» — ответим в этом чате."
)
CLIENT_SUPPORT_PROMPT = "Опишите вопрос или проблему — ответим в этом чате."
CLIENT_SUPPORT_SENT = "Сообщение отправлено. Ответим в этом чате."

# --- Settings (my choices) ---
# HTTPS: same CTA pattern as other Mini App entry points
CLIENT_SETTINGS_CATALOG_INTRO = (
    "Выберите город, услугу, арену и тренера. Нажмите кнопку ниже."
)
CLIENT_SETTINGS_TITLE = "⚙️ <b>Настройки</b>\n\nВаши текущие выборы. Нажмите кнопку, чтобы изменить."
CLIENT_SETTINGS_ROW_CITY = "📍 Город: {value}"
CLIENT_SETTINGS_ROW_SERVICE = "🎯 Услуга: {value}"
CLIENT_SETTINGS_ROW_ARENA = "🏟 Арена: {value}"
CLIENT_SETTINGS_ROW_TRAINER = "👤 Тренер: {value}"
CLIENT_SETTINGS_NOT_SELECTED = "не выбрано"
CLIENT_CHOOSE_ARENA = "Выберите арену (опционально — можно не выбирать):"
CLIENT_ARENA_UX_HINT = "Сначала откройте арену на карте, чтобы увидеть, где она находится — затем нажмите «Выбрать»."
CLIENT_ARENA_BUTTON_MAP = "🗺 На карте"
CLIENT_ARENA_BUTTON_MAP_ALL = "🗺 Показать все арены на карте"
CLIENT_ARENA_BUTTON_SELECT = "✓ Выбрать"
CLIENT_BUTTON_SETTINGS = "Настройки"
CLIENT_BUTTON_CHANGE = "Изменить"
CLIENT_BUTTON_CHOOSE_TRAINER = "Выбрать тренера"
CLIENT_BUTTON_RESET_CHOICES = "Сбросить выбор"
CLIENT_SETTINGS_RESET_DONE = "Выбор сброшен. Можете заново выбрать город, услугу и тренера."
CLIENT_SETTINGS_NEED_CITY_SERVICE = "Сначала выберите город и услугу — тогда станет доступен выбор тренера."

# --- Leave request (no suitable trainer found) ---
CLIENT_REQUEST_BUTTON_LEAVE = "Оставить заявку на подбор тренера"
CLIENT_BUTTON_LEAVE_REQUEST = "📋 Оставить заявку"
CLIENT_REQUEST_BUTTON_EMPTY_CATALOG = "Оставить заявку — мы подберём вариант"
CLIENT_REQUEST_PROMPT_COMMENT = (
    "Напишите всё, что важно для тренера: удобные день и время, возраст, цели, пожелания.\n\n"
    "Например: <i>Пн и Ср после 18:00, ребёнку 8 лет, хочу научить кататься с нуля</i>.\n\n"
    "Или нажмите «Пропустить»."
)
CLIENT_REQUEST_SKIP = "Пропустить"
CLIENT_REQUEST_NEED_CITY_SERVICE = "Сначала выберите город и услугу в «Тренеры и запись» — тогда можно оставить заявку."
CLIENT_REQUEST_SUCCESS = "Заявка принята. Когда появится подходящий тренер — напишем вам."
CLIENT_REQUEST_BACK = "◀️ В настройки"
CLIENT_BUTTON_BACK_TO_MENU = "◀️ В главное меню"

# --- My requests & responses (client sees who responded) ---
CLIENT_MY_REQUESTS_TITLE = "📋 <b>Мои заявки</b>"
CLIENT_MY_REQUESTS_WEBAPP_INTRO = "Ваши заявки и отклики тренеров. Нажмите кнопку ниже."
CLIENT_MY_REQUESTS_LIST_HINT = "Нажмите на заявку — откроются отклики тренеров: можно написать или записаться."
# Telegram: не более 100 кнопок в одной inline-клавиатуре — без «страниц» в чате.
CLIENT_MY_REQUESTS_TRUNCATED_NOTE = "\n\n<i>Показаны первые {shown} из {total}.</i>"
CLIENT_MY_REQUESTS_EMPTY = "У вас пока нет заявок. Оставьте заявку в каталоге тренеров (пустой список / низ списка / карточка тренера)."
CLIENT_MY_REQUESTS_BUTTON_LABEL = "{city}, {service}"
CLIENT_MY_REQUESTS_ROW = "{index}. 📍 {city}, {service}. {comment}"
CLIENT_MY_REQUESTS_ROW_NO_COMMENT = "{index}. 📍 {city}, {service}"
CLIENT_MY_REQUESTS_RESPONSES_HEADER = "Откликнулись ({count}):"
CLIENT_RESPONDER_LINE = "• {name}: {comment}"
CLIENT_RESPONDER_LINE_NO_COMMENT = "• {name}"
CLIENT_TRAINER_COMMENT_LABEL = "💬 Комментарий тренера: {comment}"
CLIENT_REQUEST_EDIT_DELETE_BUTTON = "✏️ Удалить / Редактировать"
CLIENT_REQUEST_EDIT_HEAD = "Редактирование заявки"
CLIENT_REQUEST_EDIT_CURRENT = "Город: {city}\nУслуга: {service}\nТекущий комментарий: {comment}"
CLIENT_REQUEST_EDIT_CURRENT_NO_COMMENT = "Город: {city}\nУслуга: {service}\nТекущий комментарий: нет"
CLIENT_REQUEST_EDIT_PROMPT = "Отправьте новое сообщение с текстом комментария для замены или нажмите «Удалить заявку»."
CLIENT_REQUEST_EDIT_CONFIRM = "Новый комментарий:\n{comment}\n\nСохранить или удалить заявку?"
CLIENT_REQUEST_EDIT_SAVE = "✅ Сохранить комментарий"
CLIENT_REQUEST_DELETE_BUTTON = "🗑 Удалить заявку"
CLIENT_REQUEST_EDIT_BACK = "◀️ Назад"
CLIENT_REQUEST_EDIT_SAVED = "Комментарий обновлён."
CLIENT_REQUEST_DELETED = "Заявка удалена."
CLIENT_BUTTON_MY_REQUESTS = "Мои заявки и отклики"
CLIENT_BUTTON_MY_BOOKINGS = "Мои записи"
# После invite/bind: клиентский хаб Mini App (`/webapp/client-home`).
CLIENT_BUTTON_TRAINER_AND_BOOKING = "Главная"

# Universal invite — registration Mini App: neutral copy (profile to continue).
CLIENT_UNIVERSAL_INVITE_UNKNOWN = (
    "👋 <b>Привет! Вас пригласил тренер {name}.</b>\n\n"
    "Заполните короткий профиль — так вы сможете продолжить и пользоваться приложением без ограничений."
)
CLIENT_UNIVERSAL_INVITE_REGISTER_BTN = "Продолжить"
# Абонементы: выданные тренером, список в Mini App
CLIENT_PASSES_INFO = (
    "Абонементы — это карточки с условиями у каждого тренера в каталоге. "
    "Покупка и оплата только напрямую у тренера, не через бота."
)
CLIENT_MY_PASSES_INTRO = "📦 Ваши абонементы: остаток занятий, тренер, срок действия. Нажмите кнопку ниже."
CLIENT_MY_BOOKINGS_TITLE = "📋 <b>Мои записи</b>"
CLIENT_MY_BOOKINGS_CANCEL_HINT = "Отменить можно в разделе «Мои записи» или написать тренеру. Имя тренера в списке — ссылка в чат."
CLIENT_MY_BOOKINGS_WEBAPP_INTRO = "Ваши записи. Отменить можно в разделе «Мои записи» (кнопка ниже) или написать тренеру."
CLIENT_MY_BOOKINGS_EMPTY = "Здесь будут ваши занятия с адресом и напоминания. Запишитесь к тренеру через каталог или заявку."
CLIENT_MY_BOOKINGS_ROW = "{index}. {date} ({day}) {time}, {duration} мин — {trainer_display}\n   Место: {place}\n   Статус: {status}"
CLIENT_BUTTON_BACK_FROM_BOOKINGS = "◀️ В меню"
CLIENT_MY_BOOKINGS_STATUS_PENDING = "Ожидает подтверждения тренера"
CLIENT_MY_BOOKINGS_STATUS_CONFIRMED = "Подтверждено тренером"
CLIENT_BUTTON_RESPONDER_WRITE = "✉️ Написать"
CLIENT_BUTTON_RESPONDER_BOOK = "Записаться"
CLIENT_BUTTON_RESPONDER_PROFILE = "👤 Профиль"
CLIENT_BUTTON_BACK_TO_RESPONSES = "◀️ Назад к откликам"
CLIENT_BUTTON_BACK_TO_REQUESTS = "◀️ Назад к заявкам"
CLIENT_RESPONDER_NO_TG = "(тренер ещё не в боте — только запись)"
CLIENT_PICK_TRAINER_DONE = "Тренер выбран. Нажмите «Записаться» в меню или ниже, чтобы выбрать время."

# --- Trainer bot: client requests (list = Новые / В работе, tap → detail) ---
TRAINER_REQUESTS_TITLE = "📋 <b>Заявки клиентов</b>"
TRAINER_REQUESTS_FILTER_LINE = "По твоему городу и услугам из профиля."
TRAINER_REQUESTS_EMPTY = "Пока нет заявок по твоему профилю (город + услуги). Заполни профиль на сайте."
TRAINER_REQUESTS_SECTION_NEW = "📥 <b>Новые</b> — откликнись, клиент увидит тебя в списке."
TRAINER_REQUESTS_SECTION_IN_PROGRESS = "✓ <b>В работе</b> — отклик есть, можно записать клиента на слот."
TRAINER_REQUESTS_SECTION_NEW_EMPTY = "📥 Новых заявок нет."
TRAINER_REQUESTS_SECTION_IN_PROGRESS_EMPTY = "✓ В работе заявок нет."
TRAINER_REQUESTS_PAGE_BACK = "◀️ Назад"
TRAINER_REQUESTS_PAGE_NEXT = "▶️ Далее"
# Detail screen (one request)
TRAINER_REQUEST_DETAIL_HEAD = "<b>{city}</b>  ·  <b>{service}</b>"
TRAINER_REQUEST_DETAIL_COMMENT = "💬 Комментарий клиента: {comment}"
TRAINER_REQUEST_DETAIL_RESPONDED_HINT = (
    "Ты уже откликнулся на эту заявку. Клиент видит тебя в списке откликнувшихся."
)
TRAINER_REQUEST_ROW = "{index}. {city}, {service}. {comment}"
TRAINER_REQUEST_ROW_NO_COMMENT = "{index}. {city}, {service}"
TRAINER_BUTTON_REQUESTS = "📋 Заявки клиентов"
TRAINER_BUTTON_RESPOND = "💬 Ответить клиенту"
TRAINER_BUTTON_RESPOND_INDEX = "{index}. Ответить"
TRAINER_RESPONDED = "✅ Отклик отправлен"
TRAINER_RESPONDED_INDEX = "{index}. Отклик отправлен"
TRAINER_REQUESTS_BACK_TO_LIST = "◀️ К списку заявок"
TRAINER_REQUEST_WRITE_CLIENT = "✉️ Написать клиенту"
TRAINER_REQUEST_BOOK_CLIENT = "Записать клиента"
TRAINER_REQUEST_REMIND_WHEN_SLOTS = "Напомнить когда появятся слоты"
TRAINER_REQUEST_REMIND_SLOTS_SET = "Напомним, когда появятся свободные слоты — запиши клиента по этой заявке."
TRAINER_REQUEST_BOOK_CHOOSE_SLOT = "Выбери слот для записи клиента по заявке:"
TRAINER_REQUEST_BOOK_SUCCESS = "Клиент записан. Заявка закрыта, клиенту отправлено уведомление."
TRAINER_REQUEST_REMIND_HAS_SLOTS = (
    "<b>Заявка ждёт записи</b>\n\n"
    "По заявке есть свободные слоты — запиши клиента или напиши ему."
)
TRAINER_PENDING_BOOKING_REMINDER = (
    "📩 <b>Заявки ждут действий</b>\n\n"
    "Открыто: <b>{count}</b> {requests_word}. Клиент выбрал вас — назначьте время или напишите.\n\n"
    "👉 Меню бота → <b>«Заявки клиентов»</b>."
)
CLIENT_TRAINER_BOOKED_YOU = (
    "📅 <b>Вас записали на занятие</b>\n\n"
    "👤 <b>Тренер:</b> <b>{name}</b>\n"
    "📅 <b>Когда:</b> <b>{date}</b> ({day}) · {time}\n\n"
    "Адрес, отмена и детали — в <b>«Мои записи»</b>."
)


def format_client_trainer_booked_you_html(
    *,
    date: str,
    day: str,
    time: str,
    trainer_name: str,
    service_name: str | None,
    booking_price_cents: int | None,
    price_tier_label: str | None,
    arena_name: str | None,
    arena_address: str | None,
    duration_minutes: int | None,
    map_link: str | None,
) -> str:
    """Rich HTML message for client after trainer books them (ParseMode.HTML)."""
    parts: list[str] = [
        "📅 <b>Вас записали на занятие!</b>\n\n",
        f"👤 <b>Тренер:</b> <b>{html.escape(trainer_name)}</b>\n",
    ]
    dur_part = f" – <b>{int(duration_minutes)}</b> мин" if duration_minutes is not None else ""
    parts.append(f"📅 <b>Когда:</b> <b>{html.escape(date)}</b> ({html.escape(day)}) · {html.escape(time)}{dur_part}\n")

    svc_lines: list[str] = []
    svc = (service_name or "").strip()
    if svc:
        if (price_tier_label or "").strip():
            svc_lines.append(f"🎯 <b>Услуга:</b> {html.escape(svc)} · тариф: <b>{html.escape(price_tier_label)}</b>")
        else:
            svc_lines.append(f"🎯 <b>Услуга:</b> {html.escape(svc)}")
    elif (price_tier_label or "").strip():
        svc_lines.append(f"🎯 Тариф: <b>{html.escape(price_tier_label)}</b>")
    if booking_price_cents is not None:
        byn = booking_price_cents / 100.0
        ps = format_rubles_byn_display(byn)
        svc_lines.append(f"💳 <b>Цена:</b> {html.escape(ps)}")
    if svc_lines:
        parts.append("\n" + "\n".join(svc_lines) + "\n")

    venue_lines: list[str] = []
    an = (arena_name or "").strip()
    aa = (arena_address or "").strip()
    if an and aa:
        venue_lines.append(f"📍 <b>Место:</b> <b>{html.escape(an)}</b>")
        venue_lines.append(html.escape(aa))
    elif an:
        venue_lines.append(f"📍 <b>Место:</b> <b>{html.escape(an)}</b>")
    elif aa:
        venue_lines.append(f"📍 <b>Место:</b> {html.escape(aa)}")
    else:
        venue_lines.append("📍 <b>Место:</b> уточните у тренера")
    parts.append("\n" + "\n".join(venue_lines) + "\n")

    parts.append("\nАдрес, отмена и детали — в <b>«Мои записи»</b>.")
    return "".join(parts)


def build_client_trainer_booked_you_inline_keyboard(
    *,
    booking_id: int,
    map_url: str | None,
    webapp_base_url: str | None,
):
    """After trainer books the client: open «Мои записи» in Mini App + optional map (ParseMode.HTML message)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    web_ok = base.lower().startswith("https://")
    rows: list[list[InlineKeyboardButton]] = []
    if web_ok:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BUTTON_MY_BOOKINGS,
                    web_app=WebAppInfo(
                        url=f"{base}/webapp/client-bookings?open_booking={int(booking_id)}"
                    ),
                ),
            ]
        )
    if map_url:
        rows.append([InlineKeyboardButton(text=CLIENT_BUTTON_SHOW_ON_MAP, url=map_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


TRAINER_RESPOND_SUCCESS = "Отклик отправлен. Клиент увидит тебя в списке и сможет записаться или написать."
TRAINER_RESPOND_PROMPT_COMMENT = (
    "Напиши комментарий для клиента (необязательно).\n\n"
    "Например: <i>Когда появится слот на это время — запишу вас</i> или <i>Могу предложить Ср 18:00, Пт 19:00</i>.\n\n"
    "Клиент увидит это в откликах. Или нажми «Отправить без комментария»."
)
TRAINER_RESPOND_SKIP = "Отправить без комментария"
TRAINER_BUTTON_DECLINE = "❌ Отклонить"
TRAINER_REQUEST_DECLINED = "Заявка отклонена. Её больше не видно в списке."

# --- Notifications ---

# --- Morning + Sunday digest (src/application/trainer_digest_use_cases.py) ---
# Design intent: a habit-forming ritual, not a billing dump. Structure per message:
#   1) HERO (emoji + warm hook + the number that matters most)
#   2) DETAIL (scannable rows; inline tags for risks/opportunities)
#   3) ONE RECOMMENDATION (👉 — closes an open loop; always present)
# Voice rule: .cursor/rules/Product-voice.mdc  •  Edit: reuse emoji vocabulary consistently
# (☀️ morning · 🌙 weekly · ⏱ time · 📍 venue · 👋 first-timer · ⚠ risk · 💬 owed · 👉 do-this).

# --- Morning digest — auto: утренний слот (~8:00), не «за час» до вечерней тренировки; иначе digest_send_time.
TRAINER_DIGEST_MORNING_GREETING = "☀️ Доброе утро!"
TRAINER_DIGEST_MORNING_GREETING_DAY = "☀️ Добрый день!"
TRAINER_DIGEST_MORNING_GREETING_EVENING = "🌤 Добрый вечер!"
TRAINER_DIGEST_SESSION_TAG_FIRST_TIMER = "👋 первая тренировка"
TRAINER_DIGEST_SESSION_TAG_PENDING = "⚠ ждёт подтверждения"
TRAINER_DIGEST_GAP_LINE = (
    "⏱ Окно между <b>{from_time}</b> и <b>{to_time}</b> — <b>{duration}</b>."
)
TRAINER_DIGEST_OWED_LINE_REQUESTS_ONLY = (
    "💬 Ждут ответа: <b>{count}</b> {word} в каталоге."
)
TRAINER_DIGEST_OWED_LINE_CONFIRMS_ONLY = (
    "💬 Ждут твоего решения: <b>{count}</b> {word} на подтверждение."
)
TRAINER_DIGEST_OWED_LINE_BOTH = (
    "💬 Ждут ответа: <b>{req_count}</b> {req_word} в каталоге "
    "и <b>{conf_count}</b> {conf_word} на подтверждение."
)

# Morning recommendation — exactly one 👉 line, picked by priority ladder in
# trainer_digest_format._pick_morning_recommendation. Goal: close the open loop.
TRAINER_DIGEST_MORNING_REC_FIRST_TIMER = (
    "👉 Начни день с {name} — у клиента это первое занятие. "
    "Первые минуты знакомства часто решают, вернётся ли человек."
)
TRAINER_DIGEST_MORNING_REC_PENDING_CONFIRM = (
    "👉 Бронь {name} в <b>{time}</b> ещё висит без подтверждения — одно нажатие закроет."
)
TRAINER_DIGEST_MORNING_REC_PENDING_REQUESTS = (
    "👉 <b>{count}</b> {word} в каталоге ждут ответа. "
    "В первый час отклик работает лучше всего."
)
TRAINER_DIGEST_MORNING_REC_BIG_GAP = (
    "👉 Днём есть окно — хороший момент ответить на заявки или пройтись по профилю."
)
TRAINER_DIGEST_MORNING_REC_ALL_CLEAR = "👉 День собран. Хорошей работы."

# Morning LITE — 0 sessions but ≥1 open request. No run-sheet, just a nudge + rec.
TRAINER_DIGEST_MORNING_LITE_HEADER = (
    "☀️ {greet} Сегодня тренировок нет — но <b>{count}</b> {word} "
    "в каталоге ждут ответа."
)
TRAINER_DIGEST_MORNING_LITE_REC = (
    "👉 Ответ в первый час обычно решает, выберет клиент тебя или соседа."
)

# --- Sunday digest — perspective + ledger.
TRAINER_DIGEST_WEEKLY_GREETING = "🌙 Воскресный обзор."
TRAINER_DIGEST_WEEKLY_PAST_HEADER = "📊 <b>За прошедшую неделю</b>"
TRAINER_DIGEST_WEEKLY_PAST_COMPLETED = "• Провёл <b>{count}</b> {word}"
TRAINER_DIGEST_WEEKLY_PAST_CASH = "• <b>{cash}</b> наличными"
TRAINER_DIGEST_WEEKLY_PAST_PASSES = "• <b>{count}</b> {word} по абонементам"
TRAINER_DIGEST_WEEKLY_PAST_CERTS = "• <b>{cash}</b> по сертификатам"
TRAINER_DIGEST_WEEKLY_PAST_EMPTY = "• Неделя была без тренировок — бывает."

TRAINER_DIGEST_WEEKLY_UPCOMING_HEADER = "📅 <b>Впереди</b>"
TRAINER_DIGEST_WEEKLY_UPCOMING_COUNT = "• <b>{count}</b> {word} запланировано"
TRAINER_DIGEST_WEEKLY_UPCOMING_EMPTY = "• Неделя пока пустая."
TRAINER_DIGEST_WEEKLY_NEW_CLIENTS = "• Новые лица: {names}"
TRAINER_DIGEST_WEEKLY_EMPTY_DAYS = "• Полностью свободно: {days}"
TRAINER_DIGEST_WEEKLY_HEAVIEST_DAY = "• Самый плотный — {label}, {count} {word}"

# Weekly recommendation — closes the loop with one concrete move for the coming week.
TRAINER_DIGEST_WEEKLY_REC_EMPTY_DAY = (
    "👉 В {day} пусто — хороший момент написать давним клиентам или добавить слоты."
)
TRAINER_DIGEST_WEEKLY_REC_HEAVY_DAY = (
    "👉 {day} плотно — проверь, что между тренировками есть время на переезд и еду."
)
TRAINER_DIGEST_WEEKLY_REC_NEW_CLIENTS = (
    "👉 На неделе встретишь новых: {names}. "
    "Короткое сообщение накануне обычно снижает no-show."
)
TRAINER_DIGEST_WEEKLY_REC_QUIET = (
    "👉 На неделе тихо. Напишите тем, кто давно не занимался — "
    "так чаще возвращаются к регулярным тренировкам."
)
TRAINER_DIGEST_WEEKLY_REC_ALL_GOOD = (
    "👉 Неделя собрана. Воскресенье — твоё."
)

# Drought ladder (src/application/trainer_digest_use_cases.py::_weekly_drought_block).
# Appears before the weekly recommendation when triggered; case 7 = silence.
TRAINER_DIGEST_DROUGHT_OPEN_REQUESTS = (
    "💬 На неделе тихо — но тебя ждут <b>{count}</b> {word} в каталоге. "
    "Ответ в первый час обычно решает."
)
TRAINER_DIGEST_DROUGHT_CATALOG_HIDDEN = (
    "👁 На неделе пусто — и тебя сейчас не видно в каталоге. Включим обратно?"
)
TRAINER_DIGEST_DROUGHT_NO_SLOTS = (
    "📭 Клиенту сейчас не из чего выбрать: свободных окон нет на ближайшие "
    "<b>{horizon_days}</b> дней. Добавим несколько?"
)
TRAINER_DIGEST_DROUGHT_DORMANT = (
    "💭 На неделе пусто. {names} давно не появлялись — может, написать им первым?"
)
TRAINER_DIGEST_DROUGHT_PROFILE_INCOMPLETE = (
    "✏️ Сейчас затишье — хороший момент довести профиль. "
    "Клиент в каталоге видит только то, что заполнено."
)
TRAINER_DIGEST_DROUGHT_NO_TEMPLATE = (
    "🗓 Пусто. Недельный шаблон расписания пока не настроен — "
    "с ним слоты появляются автоматически."
)
TRAINER_REQUEST_NOTIFICATION = (
    "📩 <b>Новая заявка</b>\n\n"
    "<b>{city}</b> · {service}\n"
    "💬 <b>Комментарий:</b> {comment}\n\n"
    "Дальше: меню → <b>«Заявки клиентов»</b> — отклик и действия под заявкой."
)
TRAINER_REQUEST_NOTIFICATION_NO_COMMENT = (
    "📩 <b>Новая заявка</b>\n\n"
    "<b>{city}</b> · {service}\n\n"
    "Дальше: меню → <b>«Заявки клиентов»</b> — отклик и действия под заявкой."
)
TRAINER_PASS_ORDER_NOTIFICATION = (
    "📦 <b>Клиент хочет абонемент</b>\n\n"
    "<b>Клиент</b> — {client_name}\n"
    "<b>Абонемент</b> — {pass_name}\n"
    "<b>Услуга</b> — {service_line}\n\n"
    "Напишите клиенту, обсудите оплату и выдайте абонемент."
)
TRAINER_PASS_ORDER_BTN_WRITE = "✍️ Написать клиенту"
# Same row as DM link: relay still works when trainer_app polling is up (optional second tap).
TRAINER_ORDER_WRITE_VIA_BOT_BTN = "🤖 Через бота"
TRAINER_PASS_ORDER_BTN_ISSUE = "📦 Выдать абонемент"
TRAINER_ORDER_BTN_WRITE_VIA_BOT = "💬 Написать через бот"
# Pass/cert catalog pushes: «Написать клиенту» = tg:// DM; опционально «Через бота» = relay (нужен polling trainer_app).
CLIENT_REQUEST_RELAY_CHAT_PREFIX = "cq_rly:"
# Legacy inline keyboards still в чатах: «Чат не открылся» / второй шаг после старых tg://‑кнопок.
CERT_ORDER_FALLBACK_PROMPT_CALLBACK_PREFIX = "co_fb:"
CERT_ORDER_FALLBACK_DISMISS_CALLBACK_PREFIX = "co_fdx:"
# Legacy: было «Написать через бот» во втором сообщении — тот же relay, что и cq_rly:.
CERT_ORDER_FALLBACK_RELAY_CALLBACK_PREFIX = "co_rly:"
TRAINER_CERT_ORDER_BTN_IF_CHAT_BLOCKED = "💬 Чат не открылся"
TRAINER_CERT_ORDER_FALLBACK_FOLLOWUP_TEXT = (
    "Не удалось открыть личный чат. У клиента могут быть закрыты входящие сообщения.\n\n"
    "Можете связаться с клиентом через бота — кнопка ниже."
)
TRAINER_CERT_ORDER_RELAY_NO_CLIENT_TELEGRAM = (
    "У клиента нет Telegram — переписка через бота недоступна. Свяжитесь по email или в мини-приложении."
)
TRAINER_CERT_ORDER_RELAY_TRAINER_CANT_ACCESS_CLIENT = (
    "Сейчас нельзя написать этому клиенту через бота (нет активной связи в CRM)."
)
TRAINER_CERT_ORDER_FALLBACK_BTN_CANCEL = "Отмена"
TRAINER_CERT_ORDER_NOTIFICATION = (
    "🎁 <b>Клиент заказывает сертификат</b>\n\n"
    "<b>Клиент (заказчик)</b> — {client_name}\n"
    "<b>Сертификат</b> — {cert_name}\n"
    "<b>Получатель</b> — {recipient_name}\n"
    "<b>Email для PDF</b> — {recipient_email}\n\n"
    "Свяжитесь для оплаты и выдайте сертификат."
)
TRAINER_CERT_ORDER_BTN_ISSUE = "🎁 Выдать сертификат"
CLIENT_RESPONSE_NOTIFICATION = (
    "📩 <b>Отклик по вашей заявке</b>\n\n"
    "Тренер ответил — откройте список откликов кнопкой ниже: там можно написать или записаться."
)
CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT = (
    "📩 <b>Отклик по вашей заявке</b>\n\n"
    "<b>{responder_name}</b>\n"
    "{comment}\n\n"
    "Ниже — все отклики: можно написать тренеру или выбрать запись."
)
CLIENT_RESPONSE_BUTTON_VIEW = "👤 Посмотреть отклики"
CLIENT_NO_RESPONSE_REMINDER = (
    "🕒 <b>Пока без откликов</b>\n\n"
    "Мы ещё раз напомнили <b>тренерам</b> о вашей заявке.\n\n"
    "Хотите не ждать? Откройте каталог и запишитесь сами — как только кто-то откликнется, пришлём отдельное сообщение."
)
CLIENT_BUTTON_OPEN_CATALOG_WEBAPP = "📅 Открыть каталог"
CLIENT_BOOKING_CANCELLED_BY_TRAINER = (
    "❌ <b>Запись отменена тренером</b>\n\n"
    "📅 Было: <b>{date}</b> ({day}) · {time}\n\n"
    "Выберите другое время или тренера: <b>«Тренеры и запись»</b> в меню бота."
)
CLIENT_BOOKING_CANCELLED_BY_SELF = (
    "🗑️ <b>Запись отменена</b>\n\n"
    "📅 Было: <b>{date}</b> ({day}) · {time}\n\n"
    "Ниже можно сразу выбрать новое время в каталоге."
)
# Same booking details when WebApp URL is unavailable (no inline button promised).
CLIENT_BOOKING_CANCELLED_BY_SELF_MENU = (
    "🗑️ <b>Запись отменена</b>\n\n"
    "📅 Было: <b>{date}</b> ({day}) · {time}\n\n"
    "Чтобы записаться снова, откройте <b>«Тренеры и запись»</b> в меню бота."
)
CLIENT_BUTTON_BOOK_AGAIN = "📅 Записаться снова"
# Hub rhythm: trainer picks clients → push from client bot with WebApp booking entry
CLIENT_FILL_SLOTS_INVITE_BTN_BOOK = "Записаться"
CLIENT_BUTTON_SHOW_ON_MAP = "Показать на карте"
CLIENT_BOOKING_CONFIRMED_BTN_MAP = "🗺 На карте"
CLIENT_REMINDER_BTN_SHOW_ON_MAP = "🗺 На карте"
CLIENT_BOOKING_CONFIRMED_BTN_DETAILS = "📋 Детали записи"
CLIENT_BOOKING_CONFIRMED_BTN_WRITE_TRAINER = "📩 Написать тренеру"
CLIENT_DECLINE_BTN_OTHER_TIME = "📅 Другое время"
CLIENT_DECLINE_BTN_OTHER_TRAINERS = "🔍 Другие тренеры"
CLIENT_REMINDER_BTN_SHOW_ON_MAP = "🗺 На карте"
CLIENT_REMINDER_BTN_WRITE_TRAINER = "📩 Написать тренеру"
CLIENT_PASS_ISSUED_BTN_TERMS = "📄 Условия"


def build_client_booking_confirmed_inline_keyboard(
    *,
    map_url: str | None,
    trainer_telegram_id: int | None,
    booking_id: int | None = None,
    webapp_base_url: str | None = None,
):
    """Details (Mini App) and write trainer each on their own row (avoids Telegram truncating side-by-side labels); then map when URL known."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    web_ok = base.lower().startswith("https://")
    rows: list[list[InlineKeyboardButton]] = []
    if web_ok and booking_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BOOKING_CONFIRMED_BTN_DETAILS,
                    web_app=WebAppInfo(url=f"{base}/webapp/client-bookings?open_booking={int(booking_id)}"),
                )
            ]
        )
    if trainer_telegram_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BOOKING_CONFIRMED_BTN_WRITE_TRAINER,
                    url=f"tg://user?id={trainer_telegram_id}",
                )
            ]
        )
    if map_url:
        rows.append(
            [InlineKeyboardButton(text=CLIENT_BOOKING_CONFIRMED_BTN_MAP, url=map_url)]
        )
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_client_recurring_set_by_trainer_notification_html(
    *,
    trainer_name: str,
    weekday_short: str,
    time_range: str,
    service_name: str | None,
    booking_price_cents: int | None,
    price_tier_label: str | None,
    arena_display: str | None,
    materialized_count: int,
) -> str:
    """Single client-bot message when trainer sets recurring from CRM (not one push per auto-booking)."""
    tn = html.escape((trainer_name or "").strip() or "Тренер")
    ws = html.escape((weekday_short or "").strip() or "—")
    tr = html.escape((time_range or "").strip() or "—")
    parts: list[str] = [
        "✅ <b>Постоянное время закреплено</b>\n\n",
        f"👤 <b>Тренер:</b> {tn}\n",
        f"📆 <b>Каждую неделю:</b> {ws} · {tr}\n",
        _format_client_booking_confirmed_service_price_block(
            service_name, booking_price_cents, price_tier_label
        ),
    ]
    ar = (arena_display or "").strip()
    if ar:
        parts.append(f"📍 <b>Место:</b> {html.escape(ar)}\n")
    parts.append("\n")
    if int(materialized_count or 0) > 0:
        parts.append(
            "Ближайшие занятия уже в <b>«Мои записи»</b>. На каждую дату отдельное сообщение не шлём — "
            "откройте список, чтобы увидеть все запланированные слоты. Напоминания придут, как обычно.\n"
        )
    else:
        parts.append(
            "Следующие занятия появятся в <b>«Мои записи»</b>, когда в расписании тренера будет свободное окно на это время. "
            "Напоминания пришлём, как после обычной записи.\n"
        )
    return "".join(parts)


def build_client_recurring_set_inline_keyboard(
    *,
    trainer_telegram_id: int | None,
    webapp_base_url: str | None,
) -> "InlineKeyboardMarkup | None":
    """After trainer sets recurring in CRM: open My bookings + write trainer (no per-booking deep link)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    web_ok = base.lower().startswith("https://")
    rows: list[list[InlineKeyboardButton]] = []
    if web_ok:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BUTTON_MY_BOOKINGS,
                    web_app=WebAppInfo(url=f"{base}/webapp/client-bookings"),
                )
            ]
        )
    if trainer_telegram_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BOOKING_CONFIRMED_BTN_WRITE_TRAINER,
                    url=f"tg://user?id={int(trainer_telegram_id)}",
                )
            ]
        )
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_client_declined_booking_catalog_keyboard(*, webapp_base_url: str | None):
    """After decline: two catalog CTAs (same Mini App entry)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    url = f"{base}/webapp/catalog"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CLIENT_DECLINE_BTN_OTHER_TIME,
                    web_app=WebAppInfo(url=url),
                ),
                InlineKeyboardButton(
                    text=CLIENT_DECLINE_BTN_OTHER_TRAINERS,
                    web_app=WebAppInfo(url=url),
                ),
            ],
        ]
    )


def build_client_rebook_catalog_keyboard(
    *,
    webapp_base_url: str | None,
    trainer_id: int | None = None,
    service_id: int | None = None,
):
    """After client self-cancel: rebook — deep-link to that trainer's card (ignore cleared catalog session)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    url = f"{base}/webapp/catalog"
    tid = int(trainer_id) if trainer_id is not None else None
    if tid is not None and tid > 0:
        url += f"?trainer_id={tid}"
        sid = int(service_id) if service_id is not None else None
        if sid is not None and sid > 0:
            url += f"&service_id={sid}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CLIENT_BUTTON_BOOK_AGAIN,
                    web_app=WebAppInfo(url=url),
                ),
            ],
        ]
    )


def build_client_no_response_catalog_keyboard(*, webapp_base_url: str | None):
    """Gentle nudge to self-serve from catalog."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CLIENT_BUTTON_OPEN_CATALOG_WEBAPP,
                    web_app=WebAppInfo(url=f"{base}/webapp/catalog"),
                ),
            ],
        ]
    )


def format_client_fill_slots_invite_from_trainer_html(
    *,
    client_first_name: str | None,
    trainer_display_name: str,
    variant_index: int,
) -> str:
    """Client-bot HTML push: trainer asked to notify about free slots next week (Zeigarnik hub)."""
    cn = (client_first_name or "").strip()
    tn = html.escape((trainer_display_name or "").strip() or "Тренер")
    greet = f"👋 {html.escape(cn)}, привет!\n\n" if cn else ""
    foot = (
        "\n\nНажмите <b>Записаться</b> ниже — откроется запись к этому тренеру."
    )
    bodies = [
        f"{greet}<b>{tn}</b> напоминает: на следующей неделе есть свободные окна — можно выбрать время.{foot}",
        f"{greet}<b>{tn}</b> освобождает слоты на следующей неделе. Если планируете занятие — забронируйте время.{foot}",
        f"{greet}Добрый день! <b>{tn}</b> приглашает записаться на следующую неделю — в расписании появились свободные окна.{foot}",
    ]
    return bodies[int(variant_index) % len(bodies)]


def build_client_fill_slots_invite_keyboard(
    *,
    webapp_base_url: str | None,
    trainer_id: int,
    online_booking: bool,
    slot_id: int | None = None,
):
    """WebApp entry: direct book flow when online tier; otherwise catalog pinned to trainer. Optional slot_id opens book on that window."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    tid = int(trainer_id)
    if online_booking:
        url = f"{base}/webapp/book?trainer_id={tid}"
        if slot_id is not None:
            url += f"&slot_id={int(slot_id)}"
    else:
        url = f"{base}/webapp/catalog?trainer_id={tid}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=CLIENT_FILL_SLOTS_INVITE_BTN_BOOK,
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


def format_client_fill_slots_invite_freed_slot_html(
    *,
    client_first_name: str | None,
    trainer_display_name: str,
    variant_index: int,
    date_ddmm: str,
    weekday_short: str,
    time_range: str,
    service_name: str | None = None,
    arena_name: str | None = None,
) -> str:
    """Client push when trainer nudges about one concrete freed slot (hub or cancel follow-up)."""
    cn = (client_first_name or "").strip()
    tn = html.escape((trainer_display_name or "").strip() or "Тренер")
    greet = f"👋 {html.escape(cn)}, привет!\n\n" if cn else ""
    ds = html.escape(date_ddmm)
    dw = html.escape(weekday_short)
    tr = html.escape(time_range)
    when = f"{ds} ({dw}) · {tr}"
    sn = (service_name or "").strip()
    an = (arena_name or "").strip()
    lines_scope: list[str] = []
    if sn and an:
        lines_scope.append(
            f"🎯 <b>{html.escape(sn)}</b> · 📍 <b>{html.escape(an)}</b>"
        )
    elif sn:
        lines_scope.append(f"🎯 <b>{html.escape(sn)}</b>")
    elif an:
        lines_scope.append(f"📍 <b>{html.escape(an)}</b>")
    scope_block = ("\n" + "\n".join(lines_scope)) if lines_scope else ""
    if sn and an:
        fit_line = (
            "Если вам удобно прийти <b>в это время</b> на эту <b>услугу</b> и <b>площадку</b> — нажмите "
            "<b>Записаться</b> ниже. Форма откроется сразу на это окно (пока оно свободно)."
        )
    elif sn:
        fit_line = (
            "Если вам подходят <b>время</b> и <b>услуга</b> — нажмите <b>Записаться</b> ниже. "
            "Площадка будет указана в форме записи."
        )
    elif an:
        fit_line = (
            "Если вам подходят <b>время</b> и <b>площадка</b> — нажмите <b>Записаться</b> ниже. "
            "Услуга будет указана в форме записи."
        )
    else:
        fit_line = (
            "Если вам удобно прийти в это время — нажмите <b>Записаться</b> ниже. "
            "В форме будет услуга и площадка, как у тренера в расписании."
        )
    foot = f"\n\n{fit_line}"
    bodies = [
        (
            f"{greet}<b>{tn}</b> сообщает: освободилось окно <b>{when}</b>.{scope_block}{foot}"
        ),
        (
            f"{greet}Свободно окно <b>{when}</b> у <b>{tn}</b>.{scope_block}{foot}"
        ),
    ]
    return bodies[int(variant_index) % len(bodies)]


def build_trainer_client_cancel_notification_keyboard(
    *,
    webapp_base_url: str | None,
    slot_id: int,
    exclude_client_id: int,
    client_telegram_id: int | None,
):
    """
    After client self-cancel: offer mass invite (Mini App) + direct DM to the client.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    rows: list = []
    if base.lower().startswith("https://"):
        q = (
            f"open_fill_slots=1&fill_slot_id={int(slot_id)}"
            f"&fill_exclude_client_id={int(exclude_client_id)}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BUTTON_OFFER_FREED_SLOT_TO_CLIENTS,
                    web_app=WebAppInfo(url=f"{base}/webapp/trainer-home?{q}"),
                )
            ]
        )
    if client_telegram_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BUTTON_CANCEL_CLIENT_WRITE,
                    url=f"tg://user?id={int(client_telegram_id)}",
                )
            ]
        )
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


CLIENT_BOOKING_CONFIRMED_FIRST_FOR_TRAINER_BLOCK = (
    "🎉 <b>Это первая подтверждённая запись этого тренера в сервисе!</b>\n"
    "Спасибо, что помогаете ему расти 🚀\n\n"
)


def format_client_booking_confirmed_by_trainer_text(
    *,
    date: str,
    day: str,
    time: str,
    trainer_name: str,
    service_name: str | None,
    booking_price_cents: int | None,
    price_tier_label: str | None,
    arena_name: str | None,
    arena_address: str | None,
    trainer_first_booking_milestone: bool = False,
    client_display_name: str | None = None,
    client_phone: str | None = None,
    duration_minutes: int | None = None,
) -> str:
    """HTML for ParseMode.HTML; escapes user-controlled and venue strings."""
    parts: list[str] = []
    if trainer_first_booking_milestone:
        parts.append(CLIENT_BOOKING_CONFIRMED_FIRST_FOR_TRAINER_BLOCK)
    parts.append("✅ <b>Ваша запись подтверждена!</b>\n\n")
    cdn = (client_display_name or "").strip()
    if cdn:
        parts.append(f"👤 <b>ФИО:</b> {html.escape(cdn)}\n")
    cp = (client_phone or "").strip()
    if cp:
        parts.append(f"📞 <b>Телефон:</b> {html.escape(cp)}\n")
    tn = html.escape((trainer_name or "").strip() or "Тренер")
    parts.append(f"👤 <b>Тренер:</b> {tn}\n")
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    dur_part = ""
    if duration_minutes is not None:
        dur_part = f" – <b>{int(duration_minutes)}</b> мин"
    parts.append(f"📅 <b>Когда:</b> <b>{ds}</b> ({dy}) · {ts}{dur_part}\n")
    parts.append(
        _format_client_booking_confirmed_service_price_block(
            service_name, booking_price_cents, price_tier_label
        )
    )
    parts.append(_format_client_booking_confirmed_venue_block(arena_name, arena_address))
    return "".join(parts)


def _format_client_booking_confirmed_service_price_block(
    service_name: str | None,
    booking_price_cents: int | None,
    price_tier_label: str | None,
) -> str:
    lines: list[str] = []
    svc = (service_name or "").strip()
    if svc:
        if price_tier_label:
            tl = html.escape(price_tier_label.strip())
            lines.append(
                f"🎯 <b>Услуга:</b> {html.escape(svc)} · тариф: <b>{tl}</b>"
            )
        else:
            lines.append(f"🎯 <b>Услуга:</b> {html.escape(svc)}")
    elif (price_tier_label or "").strip():
        lines.append(f"🎯 <b>Услуга:</b> тариф <b>{html.escape(price_tier_label.strip())}</b>")
    if booking_price_cents is not None:
        byn = booking_price_cents / 100.0
        ps = format_rubles_byn_display(byn)
        lines.append(f"💳 <b>{html.escape(ps)}</b>")
    return ("\n".join(lines) + "\n") if lines else ""


def _format_client_booking_confirmed_venue_block(
    arena_name: str | None,
    arena_address: str | None,
) -> str:
    name = (arena_name or "").strip()
    addr = (arena_address or "").strip()
    lines: list[str] = []
    if name and addr:
        lines.append(f"📍 <b>Место:</b> <b>{html.escape(name)}</b>")
        lines.append(html.escape(addr))
    elif name:
        lines.append(f"📍 <b>Место:</b> <b>{html.escape(name)}</b>")
    elif addr:
        lines.append(f"📍 <b>Место:</b> {html.escape(addr)}")
    else:
        lines.append("📍 <b>Место:</b> уточните у тренера")
    return "\n".join(lines) + "\n"


def format_client_booking_declined_by_trainer_html(
    *,
    date: str,
    day: str,
    time: str,
    reason: str,
) -> str:
    """Client push when trainer declines a pending booking; reason is HTML-escaped."""
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    rr = html.escape((reason or "").strip() or "—")
    return (
        "❌ <b>Запись отклонена</b>\n\n"
        f"📅 <b>{ds}</b> ({dy}) · {ts}\n"
        f"💬 <b>Причина:</b> {rr}\n\n"
        "Выберите другое время или другого тренера — кнопки ниже."
    )
def _ru_sessions_word(n: int) -> str:
    """Russian plural for «N занятий» (1 занятие / 2 занятия / 5 занятий)."""
    n = abs(int(n))
    if 11 <= (n % 100) <= 14:
        return "занятий"
    m = n % 10
    if m == 1:
        return "занятие"
    if m in (2, 3, 4):
        return "занятия"
    return "занятий"


def format_client_pass_issued_html(
    *,
    product_name: str,
    sessions_total: int,
    sessions_remaining: int,
    trainer_name: str,
    service_names: list[str] | None = None,
) -> str:
    """
    Telegram HTML for client when trainer issues a pass (external payment).
    Trainer/product names are escaped.
    service_names: empty/None = unrestricted (all trainer services); otherwise list of covered services.
    """
    pn = html.escape((product_name or "").strip() or "Абонемент")
    tn = html.escape((trainer_name or "").strip() or "Тренер")
    st = int(sessions_total) if sessions_total is not None else 0
    sr = int(sessions_remaining) if sessions_remaining is not None else st
    w_st = _ru_sessions_word(st)
    names = [((n or "").strip()) for n in (service_names or []) if ((n or "").strip())]
    if not names:
        scope = "🎯 На <b>все услуги</b> тренера — подходит любая запись к нему из каталога"
    elif len(names) == 1:
        scope = (
            f"🎯 Услуга: <b>{html.escape(names[0])}</b>\n"
            "<i>Списывается при занятиях по этой услуге.</i>"
        )
    else:
        joined = ", ".join(html.escape(n) for n in names)
        scope = (
            f"🎯 Услуги: <b>{joined}</b>\n"
            "<i>Списывается при занятиях по любой из перечисленных услуг.</i>"
        )

    if st == sr:
        balance_line = f"📊 Осталось: <b>{sr}</b> / <b>{st}</b> {w_st}"
    else:
        balance_line = f"📊 Осталось: <b>{sr}</b> / <b>{st}</b> {w_st} · в пакете было <b>{st}</b> {w_st}"

    return (
        "🎫 <b>Вам выдали абонемент!</b>\n\n"
        f"👤 <b>Тренер:</b> {tn}\n"
        f"📦 <b>{pn}</b>\n"
        f"{balance_line}\n"
        f"{scope}\n\n"
        "Запишитесь через каталог или откройте абонементы в приложении — кнопки ниже."
    )


# Backwards compat (tests / old imports); prefer format_client_pass_issued_html
CLIENT_PASS_ISSUED = (
    "<b>Абонемент выдан</b>\n\n"
    "<b>{product_name}</b>\n"
    "Всего занятий: {sessions_total}, осталось: <b>{sessions_remaining}</b>\n"
    "Тренер: {trainer_name}"
)
CLIENT_BUTTON_MY_PASSES = "Мои абонементы"
CLIENT_CERTIFICATE_ISSUED = (
    "🎁 Вам выдан сертификат на <b>{amount_display}</b>. Код: <code>{code}</code>. Тренер: {trainer_name}."
)
CLIENT_BUTTON_MY_CERTIFICATES = "Мои сертификаты"
# Единое мини-приложение: абонементы + сертификаты (вкладки).
CLIENT_MENU_PASSES_CERTIFICATES_DESC = "Абонементы и сертификаты"
CLIENT_BUTTON_MY_PASSES_AND_CERTIFICATES = "Абонементы и сертификаты"
CLIENT_MY_PASSES_AND_CERTIFICATES_INTRO = (
    "📦 Абонементы — остаток занятий, тренер, срок. "
    "🎁 Сертификаты — код, номинал, активация. Нажмите кнопку ниже."
)


def format_client_certificate_bound_html(
    *,
    amount_display: str,
    code: str,
    trainer_name: str,
) -> str:
    """After certificate deep-link activation in the client bot."""
    ad = html.escape((amount_display or "").strip())
    cd = html.escape((code or "").strip())
    tn = html.escape((trainer_name or "").strip() or "Тренер")
    return (
        "🎁 <b>Сертификат привязан к вашему аккаунту.</b>\n\n"
        f"Код: <code>{cd}</code> · <b>{ad}</b>\n"
        f"👤 <b>Тренер:</b> {tn}\n\n"
        "Нажмите кнопку ниже — откроется карточка этого тренера в каталоге; запись на время — там же."
    )


# Generic / pass invite links (no cert) — name HTML-escaped in handler
CLIENT_WELCOME_INVITE = (
    "👋 <b>Привет! Вас пригласил тренер {name}.</b>\n\n"
    "{cta}"
)
CLIENT_WELCOME_BIND_FIRST_IMPRESSION = (
    "👋 <b>Вас пригласил тренер {name}.</b>\n\n"
    "<b>Ice Studio</b> — платформа для спорта и тренировок: мы соединяем тренеров и клиентов и поддерживаем развитие индустрии.\n\n"
    "Нажмите кнопку ниже — откроется главный экран приложения: записи, заявки и каталог."
)
CLIENT_FAMILY_ACCESS_WELCOME = (
    "👨‍👩‍👧 <b>Семейный доступ</b>\n\n"
    "<b>Вас пригласили подключиться к семейному аккаунту.</b>\n\n"
    "Вы в одном аккаунте с семьёй: общие записи и абонементы. "
    "Телефон в профиле общий — он был указан при регистрации.\n\n"
    "Нажмите кнопку ниже — главный экран приложения."
)
CLIENT_FAMILY_ACCESS_ALREADY_OWNER = (
    "Вы уже подключены к этому аккаунту как основной номер Telegram. "
    "Ссылку семейного доступа можно отправить другому члену семьи."
)
CLIENT_FAMILY_ACCESS_LIMIT = (
    "Семейный доступ: достигнут лимит приглашённых. Отзовите доступ у участника в приложении, чтобы пригласить другого."
)
CLIENT_WELCOME_INVITE_CTA_WEBAPP = (
    "Нажмите <b>«Записаться»</b> — выберите время и подтвердите запись в приложении."
)
CLIENT_WELCOME_INVITE_CTA_INLINE = (
    "Нажмите <b>«Записаться»</b> — покажем свободные слоты или шаги записи."
)
# Backwards compat (tests / old imports); prefer CLIENT_WELCOME_INVITE
CLIENT_WELCOME_REF = (
    "Привет! Вас пригласил тренер. Нажмите «Записаться», чтобы продолжить."
)
CLIENT_PASS_WELCOME = (
    "<b>{name}</b> пригласил вас — запишитесь на занятие или купите абонемент. Кнопки ниже."
)
CLIENT_BUTTON_BUY_PASS = "Купить абонемент"
CLIENT_WELCOME_LINK_USED = (
    "⚠️ <b>Эта ссылка уже использована или недействительна.</b>\n\n"
    "Попросите тренера прислать новую ссылку или откройте каталог сами."
)
CLIENT_WELCOME_BIND_OTHER_PROFILE = (
    "Этот Telegram уже привязан к другому профилю в системе. "
    "Если это ошибка — обратитесь к тренеру или в поддержку."
)
CLIENT_WELCOME_BIND_FAILED = (
    "Не удалось привязать профиль. Попросите тренера отправить новую пригласительную ссылку."
)
CLIENT_CERT_CODE_INVALID = "Код сертификата не найден или уже использован другим пользователем. Проверьте ссылку или обратитесь к тренеру."
CLIENT_MY_CERTIFICATES_INTRO = "🎁 Ваши сертификаты: номинал, код, статус. Нажмите кнопку ниже."
# Reminders: fixed date/time (no "через" — notifications may be delayed by poll interval).
CLIENT_REMINDER_24H = (
    "⏰ <b>Напоминание о занятии</b>\n\n"
    "📅 <b>{date}</b> ({day}) · {time}\n"
    "⏱ Длительность: {duration} мин.\n\n"
    "Адрес и детали — в <b>«Мои записи»</b> (меню бота)."
)
CLIENT_REMINDER_2H = (
    "⏱ <b>Скоро занятие</b>\n\n"
    "📅 <b>{date}</b> ({day}) · {time}\n"
    "⏱ Длительность: {duration} мин.\n\n"
    "Адрес и детали — в <b>«Мои записи»</b> (меню бота)."
)


def format_client_booking_reminder_text(
    *,
    is_soon: bool,
    sessions: list[dict],
) -> str:
    """Rich reminder copy with service, payable amount and venue. ``sessions`` is one or more same-day rows."""
    if not sessions:
        return ""
    if len(sessions) == 1:
        s0 = sessions[0]
        date, day, time_s = s0["date"], s0["day"], s0["time"]
        duration = int(s0.get("duration") or 0)
        service_name = s0.get("service_name")
        booking_price_cents = s0.get("booking_price_cents")
        arena_name = s0.get("arena_name")
        arena_address = s0.get("arena_address")
        title = (
            "⏰ <b>Скоро: занятие через ~2 ч</b>"
            if is_soon
            else "🔔 <b>Напоминание: занятие завтра</b>"
        )
        service = (service_name or "").strip() or "—"
        if booking_price_cents is not None:
            byn = booking_price_cents / 100.0
            price = format_rubles_byn_display(byn)
        else:
            price = "уточните у тренера"
        arena = (arena_name or "").strip() or "уточните у тренера"
        address = (arena_address or "").strip() or "см. «Мои записи»"
        return (
            f"{title}\n\n"
            f"📅 <b>{html.escape(date)}</b> ({html.escape(day)}) · {html.escape(time_s)} – <b>{duration}</b> мин\n"
            f"🎯 <b>{html.escape(service)}</b>\n"
            f"💳 <b>{html.escape(price)}</b>\n"
            f"📍 <b>{html.escape(arena)}</b>\n"
            f"{html.escape(address)}\n\n"
            "Сначала напишите тренеру при вопросах — карта и полный адрес в <b>«Мои записях»</b>."
        )

    title = (
        "⏰ <b>Скоро: несколько занятий</b>\n\n"
        if is_soon
        else "🔔 <b>Напоминание о занятиях в этот день</b>\n\n"
    )
    same_date = len({s.get("date") for s in sessions}) == 1
    if same_date:
        head = (
            f"📅 <b>{html.escape(str(sessions[0].get('date') or ''))}</b> "
            f"({html.escape(str(sessions[0].get('day') or ''))})\n\n"
        )
    else:
        head = ""
    lines: list[str] = []
    for s in sessions:
        t = html.escape(str(s.get("time") or "—"))
        dur = int(s.get("duration") or 0)
        svc = html.escape(((s.get("service_name") or "").strip() or "—"))
        if s.get("booking_price_cents") is not None:
            byn = int(s["booking_price_cents"]) / 100.0
            price = html.escape(format_rubles_byn_display(byn))
        else:
            price = html.escape("уточните у тренера")
        ar = html.escape(((s.get("arena_name") or "").strip() or "уточните у тренера"))
        if not same_date:
            dpart = (
                f"<b>{html.escape(str(s.get('date') or ''))}</b> ({html.escape(str(s.get('day') or ''))}) · "
            )
        else:
            dpart = ""
        lines.append(
            f"• {dpart}{t} – <b>{dur}</b> мин · <b>{svc}</b> · 💳 {price} · 📍 {ar}"
        )
    body = head + "\n".join(lines)
    return (
        f"{title}{body}\n\n"
        "Сначала напишите тренеру при вопросах — карта и полный адрес в <b>«Мои записях»</b>."
    )
# Group cohort RSVP (client bot)
CLIENT_GROUP_RSVP_INVITE = (
    "👥 <b>Групповое занятие</b>\n\n"
    "Группа: <b>{group}</b>\n"
    "📅 <b>{date}</b> ({day}) · {time}\n"
    "⏱ Длительность: {duration} мин.\n\n"
    "Подтвердите, что придёте — так тренер видит заполненность."
)
GROUP_RSVP_BUTTON_YES = "✅ Буду"
GROUP_RSVP_BUTTON_NO = "❌ Не смогу"


def format_trainer_client_repeat_gap_request_html(
    *,
    client_name: str,
    service_name: str | None,
    arena_name: str | None,
    date_str: str,
    day_str: str,
    time_str: str,
    duration_minutes: int,
) -> str:
    """Trainer push: client tapped repeat; exact slot missing but calendar gap fits the session interval."""
    svc_line = ""
    if service_name:
        svc_line = f"\n🎯 <b>Услуга:</b> {html.escape(service_name)}"
    arena_line = ""
    if arena_name:
        arena_line = f"\n📍 <b>Площадка:</b> {html.escape(arena_name)}"
    block_after_time = f"{svc_line}{arena_line}\n" if (svc_line or arena_line) else "\n"
    return (
        "🔄 <b>Клиент хочет повторить занятие</b>\n\n"
        f"<b>{html.escape(client_name)}</b> нажал «Повторить в это же время» "
        f"на ту же дату через неделю ({html.escape(date_str)}, {html.escape(day_str)}) "
        f"в {html.escape(time_str)} (~{int(duration_minutes)} мин)."
        f"{block_after_time}"
        "Важно: в вашем расписании <b>нет отдельного слота</b> с таким временем начала, "
        "при этом других пересечений на это окно нет — можно оформить запись.\n\n"
        "<b>Создать запись для клиента?</b>"
    )


def format_client_week_streak_bonus_ru(weeks: int) -> str | None:
    """Short Duolingo-style line for Telegram after completed session (retention)."""
    n = int(weeks)
    if n < 2:
        return None
    abs100 = n % 100
    abs10 = n % 10
    if abs100 >= 11 and abs100 <= 14:
        word = "недель"
    elif abs10 == 1:
        word = "неделя"
    elif abs10 >= 2 and abs10 <= 4:
        word = "недели"
    else:
        word = "недель"
    return f"\n\n🔥 <b>Уже {n} {word} подряд!</b> Так держать — загляните в «Ваша активность» на главной."


def format_client_booking_completed_notice_html(
    *,
    date: str,
    day: str,
    time: str,
    duration_minutes: int | None,
    trainer_name: str,
    service_name: str | None,
    streak_weeks: int | None = None,
) -> str:
    """Push after session is marked completed (auto or trainer)."""
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    tn = html.escape((trainer_name or "").strip() or "Тренер")
    svc = (service_name or "").strip()
    svc_line = f"🎯 <b>{html.escape(svc)}</b>\n" if svc and svc != "—" else ""
    dur_part = ""
    if duration_minutes is not None:
        dur_part = f" – <b>{int(duration_minutes)}</b> мин"
    streak_part = ""
    if streak_weeks is not None and int(streak_weeks) >= 2:
        bonus = format_client_week_streak_bonus_ru(int(streak_weeks))
        if bonus:
            streak_part = bonus
    return (
        "🏁 <b>Занятие завершено</b>\n\n"
        f"📅 <b>{ds}</b> ({dy}) · {ts}{dur_part}\n"
        f"👤 <b>Тренер:</b> {tn}\n"
        f"{svc_line}"
        f"{streak_part}"
        "\nОставьте отзыв ⭐⭐⭐⭐⭐ — кнопка ниже. Можно также написать тренеру."
    )


def build_client_booking_completed_inline_keyboard(
    *,
    webapp_base_url: str,
    trainer_id: int,
    booking_id: int,
    trainer_telegram_id: int | None,
    show_repeat_row: bool,
):
    """After session completed: feedback, optional DM trainer, optional repeat same slot next week, and book again."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=CLIENT_BUTTON_LEAVE_FEEDBACK,
                callback_data=f"feedback_booking:{int(booking_id)}",
            ),
        ],
    ]
    if trainer_telegram_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BOOKING_CONFIRMED_BTN_WRITE_TRAINER,
                    url=f"tg://user?id={int(trainer_telegram_id)}",
                ),
            ],
        )
    if show_repeat_row:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BUTTON_REPEAT_SAME_TIME,
                    callback_data=f"repeat_booking:{int(booking_id)}",
                ),
            ],
        )
    if base.lower().startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text=CLIENT_BUTTON_BOOK_AGAIN_COMPLETED,
                    web_app=WebAppInfo(url=f"{base}/webapp/catalog?trainer_id={int(trainer_id)}"),
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_client_session_milestone_notice_html(
    *,
    milestone: int,
    effort_compact_html_line: str,
    percentile_more_active: int | None,
) -> str:
    """Тёплый milestone-пуш: эмодзи, аккуратный русский, жирное на смысле и цифрах."""
    m = int(milestone)
    pct = int(percentile_more_active) if percentile_more_active is not None else None

    if m == 5:
        hook = (
            "🌟 Вы уже <b>пять раз</b> довели занятие до конца — небольшой, но уже ощутимый задел."
        )
    elif m == 10:
        hook = (
            "🔥 Это уже <b>десять завершённых занятий</b> — не разовые выходы на лёд, "
            "а Ваш устойчивый ритм."
        )
    elif m == 25:
        hook = (
            "🏆 У Вас на счёту <b>двадцать пять завершённых занятий</b> — такую длинную "
            "честную серию выдерживают немногие, и Вы среди них."
        )
    else:
        hook = f"🎯 У Вас уже <b>{m}</b> завершённых занятий — это заметный шаг."

    effort = (
        f"📊 Если прикинуть по длительности и услугам: {effort_compact_html_line} "
        f"(оценка грубая, но порядок такой)."
    )
    blocks: list[str] = [hook, effort]
    if pct is not None:
        blocks.append(
            "📈 К слову: у примерно <b>{pct}%</b> тех, кто уже хоть раз довёл занятие до конца здесь, "
            "завершённых накопилось <b>меньше</b>, чем у Вас сейчас.".format(pct=pct)
        )
    return "\n\n".join(blocks)


def build_client_session_milestone_inline_keyboard(*, webapp_base_url: str):
    """WebApp deep-link to full stats screen."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Открыть активность",
                    web_app=WebAppInfo(url=f"{base}/webapp/client-stats"),
                ),
            ],
        ]
    )


# Inactive: 10 / 30 days since last session — friendly nudge to book again (once per client per kind)
CLIENT_INACTIVE_10_DAYS = (
    "👋 <b>Давно не виделись{name}!</b>\n\n"
    "С прошлого занятия прошло больше недели — загляните в каталог и выберите удобное время.\n\n"
    "Кнопка ниже — сразу к записи."
)
CLIENT_INACTIVE_30_DAYS = (
    "📆 <b>Месяц без занятий</b>{name}\n\n"
    "Если хотите вернуться в форму — откройте каталог и запишитесь, когда будет удобно.\n\n"
    "Кнопка ниже ведёт в каталог."
)
CLIENT_INACTIVE_BTN_BOOK_NOW = "📅 Записаться сейчас"
CLIENT_BUTTON_LEAVE_FEEDBACK = "⭐ Оставить отзыв и оценку"
CLIENT_BUTTON_REPEAT_SAME_TIME = "🔄 Повторить в это же время"
CLIENT_BUTTON_BECOME_REGULAR = "📅 Стать постоянным клиентом"
CLIENT_BUTTON_BOOK_AGAIN_COMPLETED = "📅 Записаться повторно"
CLIENT_REPEAT_BOOKED = "✅ Записали вас на следующую неделю на <b>{date}</b> ({day}) {time}."
CLIENT_REPEAT_SLOT_BOOKED = (
    "На это время через неделю у тренера уже есть занятость — повторить автоматически не получится. "
    "Выберите другое время в каталоге или напишите тренеру."
)
CLIENT_REPEAT_SLOT_TAKEN_BY_REGULAR = (
    "На это время уже закреплён другой постоянный клиент. "
    "Выберите другое время в каталоге — там видны все свободные слоты."
)
CLIENT_REPEAT_NO_SLOT_YET = (
    "На это время на следующую неделю в расписании тренера пока нет окна. "
    "Когда тренер добавит слот — мы запишем вас и напишем."
)
CLIENT_REPEAT_GAP_TRAINER_NOTIFIED = (
    "Мы отправили тренеру уведомление: вы хотите прийти снова в то же время через неделю, "
    "а в расписании пока нет слота на это начало.\n\n"
    "Как только тренер подтвердит или создаст запись — вам придёт сообщение. Спасибо за терпение."
)
CLIENT_REPEAT_GAP_ALREADY_NOTIFIED = (
    "Мы уже отправили тренеру такой запрос — ждите ответа или напишите ему напрямую."
)
CLIENT_REPEAT_GAP_TRAINER_OFFLINE = (
    "Мы сохранили ваш запрос на повтор через неделю. "
    "Тренер мог не получить автоматическое уведомление в боте — напишите ему, чтобы уточнить время."
)
CLIENT_RECURRING_DONE = (
    "Вы закреплены как постоянный клиент: каждую неделю в <b>{day}</b> в {time} слот будет резервироваться за вами. "
    "Когда тренер выставит расписание на неделю — запись создастся автоматически."
)
CLIENT_RECURRING_DONE_AND_BOOKED = (
    "Вы закреплены как постоянный клиент. Мы уже записали вас на следующую неделю на <b>{date}</b> ({day}) {time} — "
    "дальше запись будет создаваться автоматически, когда тренер выставит расписание."
)
CLIENT_RECURRING_ALREADY = "У вас уже закреплено это время как постоянное."
CLIENT_RECURRING_SLOT_TAKEN = (
    "Это время уже закреплено за другим постоянным клиентом. "
    "Выберите другое время в каталоге — там видны все свободные слоты."
)
CLIENT_SLOT_AVAILABLE = (
    "🟢 <b>Свободное окно</b>\n\n"
    "📅 <b>{date}</b> ({day}) · {time}\n"
    "👤 <b>Тренер:</b> <b>{trainer_name}</b>\n\n"
    "Можно записаться в один тап — кнопка ниже."
)
CLIENT_BUTTON_BOOK_THIS_SLOT = "📅 Записаться"
CLIENT_FEEDBACK_RATE_PROMPT = "Поставьте оценку тренеру от 1 до 5 звёзд:"
CLIENT_FEEDBACK_REVIEW_PROMPT = "Напишите отзыв (необязательно) или нажмите «Пропустить»:"
CLIENT_FEEDBACK_SKIP = "Пропустить"
CLIENT_FEEDBACK_THANKS = "Спасибо за отзыв!"


def format_trainer_booking_completed_html(
    *,
    client_name: str,
    date: str,
    day: str,
    time: str,
    duration_minutes: int | None,
    service_name: str | None,
    price_tier_label: str | None,
    arena_display: str | None,
    include_quick_rebook_line: bool = False,
    append_no_pass_notice: bool = False,
) -> str:
    """Telegram HTML for trainer push after a session is marked completed."""
    cn = html.escape((client_name or "").strip() or "Клиент")
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    dur = int(duration_minutes) if duration_minutes is not None else None
    dur_part = f" – {dur} мин." if dur and dur > 0 else ""
    svc = (service_name or "").strip()
    service_line = ""
    if svc and svc != "—":
        tier = (price_tier_label or "").strip()
        if tier:
            service_line = (
                f"🎯 {html.escape(svc)} · {html.escape(tier)}\n"
            )
        else:
            service_line = f"🎯 {html.escape(svc)}\n"
    arena_line = ""
    ar = (arena_display or "").strip()
    if ar and ar != "—":
        arena_line = f"📍 {html.escape(ar)}\n"
    rebook = ""
    if include_quick_rebook_line:
        rebook = (
            "\n<b>Договорились о новом времени на месте?</b> "
            "Кнопка «Записать снова» — быстрая запись с этим клиентом на любой день.\n"
        )
    no_pass_tail = ""
    if append_no_pass_notice:
        no_pass_tail = (
            "\n\n"
            "ℹ️ <b>Занятие закрыто без списания абонемента</b>\n"
            "⚠️ <b>Причина:</b> у клиента нет активного абонемента на эту услугу."
        )
    return (
        "🏁 <b>Занятие завершено</b>\n\n"
        f"📅 <b>{ds} ({dy}) {ts}</b>{dur_part}\n"
        f"👤 <b>ФИО:</b> {cn}\n"
        f"{service_line}"
        f"{arena_line}"
        f"{rebook}"
        "\n"
        "Оставьте заметку в карточке клиента — кнопка ниже. При необходимости напишите клиенту."
        f"{no_pass_tail}"
    )


def format_trainer_booking_session_wrapup_html(
    *,
    client_name: str,
    date: str,
    day: str,
    time: str,
    duration_minutes: int | None,
    service_name: str | None,
    price_tier_label: str | None,
    booking_price_cents: int | None = None,
    arena_display: str | None,
    include_quick_rebook_line: bool = False,
) -> str:
    """Telegram HTML for trainer push before slot end (repeat booking CTA). Timing: notification_service adaptive pre-end window + fast poll."""
    cn = html.escape((client_name or "").strip() or "Клиент")
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    dur = int(duration_minutes) if duration_minutes is not None else None
    dur_part = f" – {dur} мин." if dur and dur > 0 else ""
    svc = (service_name or "").strip()
    service_line = ""
    if svc and svc != "—":
        tier = (price_tier_label or "").strip()
        if tier:
            service_line = (
                f"🎯 {html.escape(svc)} · {html.escape(tier)}\n"
            )
        else:
            service_line = f"🎯 {html.escape(svc)}\n"
    arena_line = ""
    ar = (arena_display or "").strip()
    if ar and ar != "—":
        arena_line = f"📍 {html.escape(ar)}\n"
    payment_line = ""
    if booking_price_cents is not None:
        byn = booking_price_cents / 100.0
        ps = format_rubles_byn_display(byn)
        payment_line = f"💳 <b>К оплате:</b> {html.escape(ps)}\n"
    rebook = ""
    if include_quick_rebook_line:
        rebook = (
            "\n<b>Сейчас удобный момент</b> договориться о следующем занятии и записать клиента.\n"
        )
    return (
        "⏱ <b>Занятие подходит к концу</b>\n\n"
        f"📅 <b>{ds} ({dy}) {ts}</b>{dur_part}\n"
        f"👤 <b>ФИО:</b> {cn}\n"
        f"{service_line}"
        f"{arena_line}"
        f"{payment_line}"
        f"{rebook}"
        "\n"
        "Кнопки ниже: быстрая запись и заметка в карточку клиента. Связаться с клиентом можно из карточки."
    )


def format_trainer_booking_problem_ack_html(
    *,
    client_name: str,
    preset_summary_ru: str,
    payment_class: str,
    date: str,
    day: str,
    time: str,
    service_name: str | None,
) -> str:
    """Trainer push: problem report saved — must not read like happy-path completion (E5 / FR-12)."""
    cn = html.escape((client_name or "").strip() or "Клиент")
    ps = html.escape((preset_summary_ru or "").strip() or "отчёт")
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    pc_line = ""
    pc = (payment_class or "").strip().upper()
    if pc == "PASS":
        pc_line = "💳 <b>Оплата:</b> абонемент\n"
    elif pc == "CERT":
        pc_line = "💳 <b>Оплата:</b> сертификат\n"
    elif pc == "NONE":
        pc_line = "💳 <b>Оплата:</b> без абонемента / сертификата\n"
    svc = (service_name or "").strip()
    service_line = ""
    if svc and svc != "—":
        service_line = f"🎯 <b>Услуга:</b> {html.escape(svc)}\n"
    return (
        "⚠️ <b>Проблема зафиксирована</b>\n\n"
        f"👤 <b>ФИО:</b> {cn}\n"
        f"📅 <b>Когда:</b> {ds} ({dy}) в {ts}\n"
        f"{service_line}"
        f"{pc_line}"
        f"⚠️ <b>Ситуация:</b> {ps}\n"
    )


def format_client_booking_problem_notice_html(
    *,
    date: str,
    day: str,
    time: str,
) -> str:
    """One neutral client push after trainer changes something important about this booking (Mini App)."""
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    return (
        "🔄 <b>Изменения по вашей записи</b>\n\n"
        f"📅 <b>{ds}</b> ({dy}) · {ts} — тренер обновил данные.\n\n"
        "Откройте <b>«Мои записи»</b> в меню бота, чтобы увидеть актуальные детали.\n\n"
        "Если что-то смущает — напишите тренеру."
    )


def format_trainer_client_no_show_ack_html(
    *,
    client_name: str,
    outcome_line_ru: str,
    payment_class: str,
    date: str,
    day: str,
    time: str,
    service_name: str | None,
    variant: str | None = None,
) -> str:
    """Trainer push after PASS/CERT «Клиент не пришёл» (booking_client_no_show).

    `variant` keeps backward/forward compatibility with callers that classify
    save-flow branches (skip/redeem before/after). Trainer copy itself is driven
    by `outcome_line_ru`, so we intentionally don't branch by variant here.
    """
    _ = variant
    cn = html.escape((client_name or "").strip() or "Клиент")
    ol = html.escape((outcome_line_ru or "").strip())
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    pc_line = ""
    pc = (payment_class or "").strip().upper()
    if pc == "PASS":
        pc_line = "💳 <b>Оплата:</b> абонемент\n"
    elif pc == "CERT":
        pc_line = "💳 <b>Оплата:</b> сертификат\n"
    svc = (service_name or "").strip()
    service_line = ""
    if svc and svc != "—":
        service_line = f"🎯 <b>Услуга:</b> {html.escape(svc)}\n"
    return (
        "✅ <b>Учёт «клиент не пришёл» сохранён</b>\n\n"
        f"👤 <b>ФИО:</b> {cn}\n"
        f"📅 <b>Когда:</b> {ds} ({dy}) в {ts}\n"
        f"{service_line}"
        f"{pc_line}"
        f"ℹ️ <b>Результат:</b> {ol}\n\n"
        "<i>Клиент получил уведомление об изменении статуса.</i>"
    )


def format_client_booking_no_show_notice_html(
    *,
    variant: str,
    payment_class: str,
    date: str,
    day: str,
    time: str,
    service_name: str | None,
) -> str:
    """
    Client push after trainer saves PASS/CERT no-show + deduct choice.
    variant: skip_before | skip_after | redeem_before | redeem_after
    """
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    pc = (payment_class or "").strip().upper()
    svc = (service_name or "").strip()
    service_line = ""
    if svc and svc != "—":
        service_line = f"🎯 <b>Услуга:</b> <b>{html.escape(svc)}</b>\n"

    if variant == "skip_before":
        title = "⚠️ Запись без списания"
        if pc == "PASS":
            body = (
                "Тренер отметил, что вы не пришли.\n"
                "💳 Списание с абонемента по этой записи <b>не выполняется</b>."
            )
        else:
            body = (
                "Тренер отметил, что вы не пришли.\n"
                "💳 Списание с сертификата по этой записи <b>не выполняется</b>."
            )
    elif variant == "skip_after":
        title = "✅ Занятие возвращено"
        if pc == "PASS":
            body = (
                "Тренер <b>вернул занятие</b> на абонемент: списание по записи отменено, занятие снова в вашем пакете."
            )
        else:
            body = "Тренер <b>вернул средства</b> на баланс сертификата по этой записи."
    elif variant == "redeem_before":
        title = "⚠️ Вас не было на занятии"
        if pc == "PASS":
            body = "Тренер отметил отсутствие. <b>Занятие будет списано с абонемента.</b>"
        else:
            body = "Тренер отметил отсутствие. <b>Сумма будет списана с сертификата.</b>"
    elif variant == "redeem_after":
        title = "📉 Занятие учтено как использованное" if pc == "PASS" else "📉 Списание по записи сохранено"
        if pc == "PASS":
            body = "Списание с абонемента по этой записи <b>оставлено</b> — занятие учтено как использованное."
        else:
            body = "Списание с сертификата по этой записи <b>оставлено</b> — сумма по занятию учтена."
    else:
        title = "Обновление по записи"
        body = "Тренер обновил учёт по записи. Подробности — в «Мои записи»."

    tb = html.escape(title)
    return (
        f"<b>{tb}</b>\n\n"
        f"{body}\n\n"
        f"📅 <b>{ds}</b> ({dy}) · {ts}\n"
        f"{service_line}"
        "\nПодробности — в <b>«Мои записи»</b> в меню бота."
    )


TRAINER_BUTTON_OPEN_SCHEDULE_PROBLEM = "🔍 Посмотреть детали"
TRAINER_NO_PASS_FOR_SERVICE = (
    "ℹ️ <b>Занятие закрыто без списания абонемента</b>\n\n"
    "👤 <b>ФИО:</b> {client_name}\n"
    "📅 <b>Когда:</b> {date} · {time}\n"
    "🎯 <b>Услуга:</b> {service_name}\n\n"
    "⚠️ <b>Причина:</b> у клиента нет активного абонемента на эту услугу."
)
TRAINER_BUTTON_LEAVE_FEEDBACK = "🌟 Оставить отзыв"
TRAINER_BUTTON_BOOK_SAME_TIME_NEXT_WEEK = "🔄 Записать на то же время"
TRAINER_BUTTON_BOOK_AGAIN = "📅 Записать снова"
TRAINER_BUTTON_CLIENT_CARD_WEBAPP = "👤 Карточка"
TRAINER_REPEAT_BOOKING_OK = (
    "✅ Клиент записан на <b>{date}</b> ({day}) в {time}."
)
TRAINER_REPEAT_BOOKING_NOT_FOUND = "Запись не найдена или уже недоступна."
TRAINER_REPEAT_BOOKING_SLOT_BOOKED = (
    "На это время через неделю слот уже занят — откройте расписание в приложении."
)
TRAINER_REPEAT_BOOKING_NO_SERVICE = (
    "Не удалось подобрать услугу для записи. Добавьте услугу в профиле или запишите из расписания."
)
TRAINER_REPEAT_BOOKING_CREATE_FAILED = "Не удалось создать запись. Попробуйте из расписания."
TRAINER_REPEAT_BOOKING_PRICE_TIER = (
    "Для этой услуги несколько тарифов — запишите клиента из расписания в мини-приложении."
)
TRAINER_REPEAT_BOOKING_SCHEDULE_ERROR = "Не удалось создать слот: {detail}"
TRAINER_FEEDBACK_PROMPT = "Напиши отзыв о занятии (необязательно, можно коротко):"
TRAINER_FEEDBACK_THANKS = "Спасибо! Отзыв сохранён."
TRAINER_START_WELCOME = (
    "👋 Привет!\n\n"
    "Ты в боте как тренер. Дальше — <b>меню слева от поля ввода</b>: расписание, заявки, записи, клиенты.\n\n"
    "Коротко по разделам: /guide"
)
TRAINER_ONLY_VIA_SITE = "Этот бот только для тренеров. Подключение по ссылке с сайта после регистрации и оплаты."
# После привязки по ссылке: без обещания полного меню (гейт может быть закрыт).
TRAINER_LINK_SUCCESS = (
    "Аккаунт привязан к этому Telegram.\n\n"
    "Чеклист «Первые шаги» — в «Обзор», статус и анкета — в «Профиль» в меню. Помощь: /guide"
)
# Только если тренер уже active — честно про все пункты меню.
TRAINER_LINK_SUCCESS_ACTIVE = (
    "✅ <b>Telegram подключён</b>\n\n"
    "Основное — в <b>меню слева</b>: расписание, заявки, записи, клиенты. "
    "Коротко по разделам: /guide"
)
# Единый «премиальный» онбординг после первой привязки по ссылке (не active) — герой + шаг ниже.
TRAINER_AFTER_LINK_HERO = (
    "🤝 <b>Платформа, которую строим вместе с тренерами</b>\n\n"
    "Мы делаем её с практикующими специалистами — чтобы уйти от хаоса в записи, "
    "не терять клиентов и сделать работу системной.\n\n"
    "<b>Что внутри:</b>\n"
    "— онлайн-запись и каталог для привлечения клиентов\n"
    "— расписание, CRM, абонементы и сертификаты\n"
    "— аналитика дохода и трафика\n\n"
    "Ты здесь не просто пользователь — твой опыт напрямую влияет на то, "
    "как платформа работает для всей индустрии.\n\n"
    "Начни с <b>«Обзор»</b> (<b>/home</b>) — там «Первые шаги» и сразу <b>пробный период на полном тарифе</b>."
)
TRAINER_AFTER_LINK_STEP_BOOKING_READY = (
    "<b>Сейчас</b>: базовый профиль готов — в мини-приложении уже можно настроить слоты и сделать тестовую запись. "
    "Дополни анкету позже и отправь на проверку, когда захочешь попасть в каталог.\n\n"
    "Открой <b>«Обзор»</b> ниже."
)
TRAINER_AFTER_LINK_STEP_INVITE_SUBMIT = (
    "<b>Сейчас</b>: анкета почти готова — открой <b>«Обзор»</b>, зайди в <b>«Профиль»</b> в мини-приложении "
    "и сохрани анкету: заявка на проверку уйдёт автоматически. Обычно ответ в течение рабочего дня."
)
TRAINER_AFTER_LINK_STEP_PENDING = (
    "<b>Сейчас</b>: анкета на проверке у команды. Ничего нажимать не нужно — когда одобрят, "
    "разделы в меню слева откроются сами. Статус смотри в профиле в приложении."
)
TRAINER_AFTER_LINK_STEP_NEEDS_EDIT = (
    "<b>Сейчас</b>: нужны правки по анкете.\n\n"
    "<b>Комментарий команды:</b>\n{feedback}\n\n"
    "Внеси изменения в профиле в мини-приложении и снова отправь на модерацию."
)
TRAINER_AFTER_LINK_STEP_AWAITING_ACTIVATION = (
    "<b>Сейчас</b>: профиль в порядке, остались организационные шаги (договор / подключение). "
    "Когда их закроют — всё откроется автоматически. Вопросы: /guide"
)
TRAINER_AFTER_LINK_STEP_DEACTIVATED = (
    "<b>Сейчас</b>: аккаунт деактивирован. Если это ошибка — напиши в поддержку через /guide."
)
TRAINER_LINK_INVALID = "Ссылка недействительна или уже использована. Получи новую на сайте после оплаты."
TRAINER_LINK_TELEGRAM_CONFLICT = (
    "Этот Telegram уже привязан к <b>другому</b> профилю тренера в системе.\n\n"
    "Если ты уже работаешь в боте — просто открой чат и пользуйся меню (команда /start без ссылки). "
    "Если это ошибка — напиши в поддержку: /guide"
)
# После первой привязки по ссылке: активируется полный доступ на пробный период.
TRAINER_WELCOME_TRIAL_ACTIVATED = (
    "🎁 <b>Пробный период — {tier_name}</b>\n\n"
    "До <b>{expires_date}</b> у тебя открыт полный доступ ко всем модулям платформы: "
    "CRM, онлайн-запись, абонементы, сертификаты, аналитика и группы.\n\n"
    "Когда пробный период закончится, собери свой план в разделе "
    "<b>«Подписка»</b> в меню бота — оставь только то, что реально используешь."
)
TRAINER_FALLBACK = "Используй меню слева от поля ввода — там все разделы. Помощь: /guide"

# Trainer: errors and hints
TRAINER_ERROR_BOOKING_NOT_FOUND = "Запись не найдена. Обнови «Моё расписание» в приложении."
TRAINER_ERROR_CANCEL_FAILED = "Не удалось отменить запись (уже отменена или не найдена). Обнови расписание в приложении."
TRAINER_ERROR_BOOKING_CLOSED_OR_NOT_FOUND = "Запись не найдена или уже закрыта. Открой «Моё расписание» в приложении снова."
TRAINER_ERROR_FEEDBACK_SAVE_FAILED = "Не удалось сохранить отзыв. Попробуй ещё раз или пропусти."
TRAINER_ERROR_RESPOND_FAILED = "Не удалось откликнуться (заявка уже закрыта или отклик уже был). Обнови «Заявки клиентов»."
TRAINER_ERROR_NO_SERVICES = (
    "У тебя не указана ни одна услуга. Добавь услугу в профиле в мини-приложении или в личном кабинете на сайте."
)
TRAINER_ERROR_REQUEST_GONE = (
    "Заявка не найдена или уже закрыта. Открой «Заявки клиентов» заново."
)
TRAINER_REQUEST_BOOK_NO_SLOTS_TWO_WEEKS = (
    "Нет свободных слотов на ближайшие 2 недели. Добавь слоты в разделе «Расписание»."
)
TRAINER_ERROR_REQUEST_BOOK_PAYLOAD = (
    "Не удалось обработать выбор. Открой список заявок и попробуй снова."
)
TRAINER_ERROR_REQUEST_BOOK_PAYLOAD_SHORT = "Не удалось обработать выбор. Попробуй снова."
TRAINER_ERROR_SLOT_TAKEN_FOR_REQUEST = (
    "Слот уже занят или недоступен. Выбери другой слот из списка."
)

# Trainer: Web App intros (HTTPS) — informal «ты» like TRAINER_START_WELCOME
TRAINER_EDITOR_OPEN_HINT = (
    "Открой <b>Расписание</b> через меню слева от поля ввода (или снова команду /editor) — "
    "там шаблон недели, календарь слотов и применение на неделю. "
    "По клику на свободный слот можно записать клиента."
)
TRAINER_BOOKINGS_OPEN_WEBAPP = (
    "Открой <b>«Моё расписание»</b> — занятые слоты с деталями записи: подтвердить, отменить, провести занятие, написать клиенту."
)
# When WEBAPP_BASE_URL is not HTTPS: chat list only; full «slots + booking actions» UI is in Mini App.
TRAINER_BOOKINGS_CHAT_MODE_INTRO = (
    "Полный сценарий — слоты и записи в одном экране — доступен в мини-приложении при HTTPS (продакшен). "
    "Сейчас ниже — краткий список в чате.\n\n"
    "Подробности по командам: /guide"
)
TRAINER_HOME_OPEN_WEBAPP = (
    "<b>Обзор</b> — ближайшие записи и быстрые переходы в расписание, клиентов, заявки и другие разделы."
)
TRAINER_BUTTON_HOME_WEBAPP = "Открыть обзор"
# Telegram chat menu button (left of input); short label, max ~64 chars.
TRAINER_MENU_BUTTON_HUB = "Обзор"
TRAINER_HOME_HTTPS_REQUIRED = (
    "Экран «Обзор» доступен при HTTPS (нужен WEBAPP_BASE_URL в продакшене)."
)
TRAINER_CLIENTS_HTTPS_REQUIRED = (
    "Раздел «Мои клиенты» доступен при HTTPS (нужен WEBAPP_BASE_URL в продакшене)."
)
TRAINER_CLIENTS_OPEN_WEBAPP = (
    "Открой список клиентов с записями: там видно телефон и последнее занятие."
)
TRAINER_REQUESTS_OPEN_WEBAPP = (
    "Открой «Заявки клиентов» — там можно откликнуться, записать клиента на слот или отклонить заявку."
)
TRAINER_PASSES_INTRO_WEBAPP = (
    "Настрой абонементы (N занятий за цену) и сертификаты (номинал на сумму или «любая сумма»). "
    "Клиенты видят это в карточке тренера."
)
TRAINER_PASSES_HTTPS_REQUIRED = (
    "Чтобы настроить абонементы, нужен HTTPS (открой приложение в продакшене)."
)

# Trainer: /guide — support + FAQ (FAQ Mini App wired later)
TRAINER_GUIDE = (
    "По любому вопросу и идеям по улучшению пиши в <b>поддержку</b>.\n\n"
    "Ответы на частые вопросы — кнопка <b>FAQ</b> ниже."
)
TRAINER_FAQ_COMING_SOON = (
    "Раздел FAQ скоро откроется в отдельном мини-приложении. Пока заглушка — следи за обновлениями."
)
TRAINER_SUPPORT_PROMPT = "Опиши вопрос или проблему — ответим в этом чате."
TRAINER_SUPPORT_SENT = "Сообщение отправлено. Ответим в этом чате."
TRAINER_SUPPORT_REPLY_INTRO_HTML = "📩 <b>Ответ поддержки</b>\n\n"
TRAINER_SUPPORT_REPLY_GO_PAY = "💳 Перейти к оплате"

# Trainer: invite clients from DM → client bot deep link + catalog URL (see trainer_invite_links.py)
TRAINER_INVITE_BUTTON = "📣 Пригласить клиента"
TRAINER_INVITE_INTRO_HTML = (
    "📣 <b>Пригласить клиента</b>\n\n"
    "Чтобы перевести переписку из Direct в продукт: <b>перешли клиенту следующее сообщение</b> целиком "
    "или скопируй из него текст.\n\n"
    "<i>Первая ссылка — вход в клиентский бот сразу на твой профиль. Вторая — страница каталога "
    "(появляется при HTTPS в продакшене).</i>"
)
TRAINER_INVITE_PLAIN_CLIENT_WITH_CATALOG = (
    "Привет! Записаться ко мне удобнее через бота — там слоты и статусы записей.\n\n"
    "Открыть бота (сразу мой профиль):\n"
    "{deep_link}\n\n"
    "Каталог тренеров:\n"
    "{catalog_url}"
)
TRAINER_INVITE_PLAIN_CLIENT_NO_CATALOG = (
    "Привет! Записаться ко мне удобнее через бота — там слоты и статусы записей.\n\n"
    "Открыть бота (сразу мой профиль):\n"
    "{deep_link}\n\n"
    "Дальше в боте: меню слева → «Тренеры и запись»."
)
TRAINER_INVITE_ERR_NO_CLIENT_BOT_USERNAME = (
    "Не настроено имя клиентского бота для ссылок. Администратору: задайте <code>CLIENT_BOT_USERNAME</code> "
    "в окружении (как в адресе t.me, <b>без</b> символа @)."
)
TRAINER_INVITE_ERR_PROFILE_INCOMPLETE = (
    "Не получилось собрать ссылку: в профиле нужны <b>город</b> и хотя бы одна <b>услуга</b>. "
    "Укажи в профиле в мини-приложении или в кабинете на сайте и снова нажми «Пригласить клиента»."
)

# Trainer: access gate (until profile complete + moderation approved)
# Tone: «ты», коротко; без дублирования тревоги между /start, middleware и профилем в приложении.
TRAINER_GATE_CALLBACK_BLOCKED = (
    "Этот раздел пока закрыт. Сначала заполни анкету и дождись одобрения — открой «Профиль» в меню."
)
TRAINER_GATE_BLOCKED_PROFILE = (
    "Расписание, заявки и записи закрыты: в анкете не хватает обязательных полей.\n\n"
    "Открой профиль в мини-приложении (кнопка «Профиль» в меню) — там видно, что добить."
)
TRAINER_GATE_BOOKING_READY = (
    "В <b>мини-приложении</b> уже можно открыть расписание и сделать первые записи — то же доступно и "
    "в этом чате (заметки, приглашения клиентов и разделы меню).\n\n"
    "Чтобы тебя увидели в <b>общем каталоге</b>, заполни анкету и дождись одобрения — статус в «Профиле» в приложении.\n\n"
    "Открой <b>«Обзор»</b> или <b>«Профиль»</b> в меню слева."
)
# Полная анкета, но заявка на модерацию ещё не ушла (moderation_submitted_at пустой): в Mini App отправка после «Сохранить».
TRAINER_GATE_INVITE_SUBMIT = (
    "Анкета заполнена, но заявка на проверку ещё не отправлена. Открой «Профиль» в меню и в мини-приложении "
    "нажми «Сохранить» — когда всё готово, заявка уйдёт модератору автоматически.\n\n"
    "Обычно ответ в течение рабочего дня. Статус смотри в профиле в приложении."
)
# Анкета отправлена, ждём модератора (без комментария «нужны правки»).
TRAINER_GATE_PENDING_MODERATION = (
    "Анкета на проверке. Ничего делать не нужно — дождись решения. "
    "Когда одобрят, разделы откроются сами. Статус смотри в профиле в приложении."
)
# Комментарий модератора при «нужны правки» (moderation_feedback).
TRAINER_GATE_NEEDS_EDIT = (
    "Нужны правки по анкете.\n\n"
    "<b>Комментарий модератора:</b>\n{feedback}\n\n"
    "Исправь в профиле в мини-приложении или в личном кабинете на сайте и снова отправь на модерацию."
)
# Backwards-compatible name (тот же шаблон с {feedback}).
TRAINER_GATE_PENDING_MODERATION_WITH_FEEDBACK = TRAINER_GATE_NEEDS_EDIT
# Статус pending_contract / pending_payment — не этап проверки анкеты.
TRAINER_GATE_AWAITING_ACTIVATION = (
    "Аккаунт ещё не полностью подключён (договор или оплата). "
    "Когда всё оформят — откроется полный функционал. Вопросы: /guide"
)
TRAINER_GATE_DEACTIVATED = "Аккаунт деактивирован. Если это ошибка — напиши в поддержку: /guide."
TRAINER_PROFILE_CARD = (
    "<b>Профиль тренера #{trainer_id}</b>\n"
    "Статус в системе: <b>{status_label}</b>\n\n"
    "{gate_hint}"
)
TRAINER_PROFILE_ACTIVE_HINT = (
    "Полный доступ к функциям бота открыт — можно работать."
)
TRAINER_PROFILE_SITE_HINT = "Личный кабинет (редактирование профиля): {url}"
TRAINER_PROFILE_BTN_MINI_APP = "📋 Профиль"
TRAINER_PROFILE_MINI_APP_HINT = "Анкета, фото и модерация — в кнопке ниже."
TRAINER_PROFILE_HTTPS_REQUIRED = (
    "Чтобы открыть профиль в приложении, нужен HTTPS: задайте <code>WEBAPP_BASE_URL</code> в продакшене."
)
TRAINER_MYPROFILE_INTRO = "Открой профиль — там анкета, фото и отправка на модерацию."
TRAINER_PROFILE_WIZARD_DEPRECATED = (
    "Старый многошаговый мастер в чате отключён. Открой профиль в Mini App — кнопка ниже."
)
TRAINER_CANCEL_IDLE = "Нечего отменять. Профиль — в меню."

# --- Admin bot: trainer moderation ---
ADMIN_START = (
    "Привет! Это админ-бот для модерации тренеров.\n\n"
    "Команды:\n"
    "/pending — показать тренеров на модерацию.\n"
    "/subscription_invoices — заявки на подписку (активировать / отклонить кнопками).\n"
    "/grant_subscription &lt;trainer_id&gt; — выдать подписку конкретному тренеру.\n"
    "/problem_reports — аудит отчётов «проблема с клиентом» (E6)."
)
ADMIN_NO_ACCESS = "У вас нет доступа к этому боту."
ADMIN_PROBLEM_REPORTS_TITLE = "📋 <b>Отчёты «проблема с клиентом»</b> (аудит, E6)\n\n"
ADMIN_PROBLEM_REPORTS_FILTER_BLACKLIST = "Фильтр: только кандидаты в чёрный список.\n\n"
ADMIN_PROBLEM_REPORTS_EMPTY = "Записей нет."
ADMIN_PROBLEM_REPORTS_LINE = (
    "{n}. отчёт <code>{rid}</code> · запись <code>{bid}</code> · тренер <code>{tid}</code>\n"
    "   {preset} · {pclass} · {bl} · {status}\n"
    "   слот {slot} · {created}\n"
)
ADMIN_PROBLEM_REPORTS_FOOTER = (
    "\n<i>Показано {shown} из {total}. Параметры: "
    "<code>/problem_reports</code> — все; "
    "<code>/problem_reports blacklist</code> — кандидаты blacklist; "
    "число в конце — смещение (offset) для листинга.</i>"
)
ADMIN_VERSION_TITLE = "🔧 <b>Версия и health</b>\n"
ADMIN_VERSION_DEPLOY = "• Деплой: <code>{deploy}</code>"
ADMIN_VERSION_SENTRY_ENV = "• Sentry environment: <code>{env}</code>"
ADMIN_VERSION_API_HEALTH = (
    "• API <code>GET /health</code>:\n"
    "  status=<code>{status}</code>, db=<code>{db}</code>, s3=<code>{s3}</code>"
)
ADMIN_VERSION_API_ERROR = "• API: <b>недоступен</b> — {error}"
ADMIN_VERSION_NOTIFICATION_SERVICE = (
    "• Notification-service: отдельный процесс без HTTP; пульс в боте не показывается "
    "(логи/панель хостинга)."
)
ADMIN_PENDING_EMPTY = "Нет тренеров в очереди на модерацию."
# Legacy short card (moderation UI uses src.bot.admin_moderation_card.format_admin_trainer_moderation_caption).
ADMIN_TRAINER_CARD = (
    "<b>Тренер #{id}</b>\n"
    "Имя: {name}\n"
    "Возраст: {age}\n"
    "Опыт: {experience}\n\n"
    "{description}"
)
# Prepended to full moderation caption when trainer submits for review (async notify).
ADMIN_NOTIFY_NEW_MODERATION_PREFIX = "🆕 <b>Отправлено на модерацию</b>\n\n"
ADMIN_BUTTON_APPROVE = "✅ Одобрить"
ADMIN_BUTTON_REJECT = "❌ Отклонить"
ADMIN_BUTTON_NEEDS_EDIT = "✏️ Нужны правки"
ADMIN_APPROVED = "Тренер одобрен и станет виден клиентам."
ADMIN_REJECTED = "Тренер отклонён и не будет виден клиентам."
ADMIN_NEEDS_EDIT_PROMPT = (
    "Напишите текст фидбека для тренера — он увидит его в мини-приложении «Профиль» "
    "и получит уведомление в этом боте."
)
ADMIN_NEEDS_EDIT_DONE = (
    "Фидбек сохранён. Тренер остаётся в статусе «на модерации»; текст показан в профиле и отправлен в Telegram."
)
ADMIN_NEEDS_EDIT_CANCELLED = "Отменено."
TRAINER_EDUCATION_MODERATION_APPROVED = (
    "✅ <b>Образование одобрено</b>\n\n"
    "Ваш профиль теперь показывает раздел в каталоге — клиенты видят квалификацию. 🎓"
)
TRAINER_EDUCATION_MODERATION_REJECTED = (
    "⚠️ <b>Образование требует доработки</b>\n\n"
    "<b>Комментарий:</b>\n{reason}\n\n"
    "Загрузите правки в мини-приложении «Профиль»."
)
# Push to trainer bot when admin saves «Нужны правки» comment (moderation_feedback).
TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH = (
    "✏️ <b>Правки по анкете</b>\n\n"
    "🤔 <b>Просьбы модератора:</b>\n{feedback}"
)
TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH_FOOTER = "\n\nОткройте мини-приложение «Профиль» — кнопка ниже."
TRAINER_STATS_BTN_MINI_APP = "📊 Статистика"
TRAINER_MODERATION_PROFILE_APPROVED = (
    "🎊 <b>Поздравляем — анкета принята!</b>\n\n"
    "Это важный шаг: вы <b>в каталоге</b>. Новые клиенты могут <b>сами находить</b> вашу карточку, смотреть услуги "
    "и записываться — для вас это <b>дополнительный поток из каталога</b> и больше возможностей переводить интерес "
    "в <b>записи и оплату</b>.\n\n"
    "📈 В разделе <b>«Статистика»</b> смотрите, сколько раз открывали профиль и сколько раз переходили в ваш "
    "Telegram — так проще понимать, откуда приходит трафик."
)
TRAINER_MODERATION_PROFILE_REJECTED = (
    "❌ <b>Анкета не прошла модерацию</b>\n\n"
    "Профиль пока не отображается в каталоге.\n\n"
    "<b>Причина:</b> см. комментарий модератора в профиле или напишите в поддержку: /guide"
)

# Trainer schedule (by calendar week + template for quick apply)
TRAINER_SCHEDULE_TITLE = (
    "📅 <b>Расписание по неделям</b>\n\n"
    "<b>Как устроено:</b>\n"
    "• <b>Шаблон</b> — образец недели (день + время). Его можно менять в любой момент.\n"
    "• <b>Недели</b> — текущая и следующая. Слоты на неделю можно добавлять вручную по дням или применить шаблон.\n\n"
    "«Применить на неделю из шаблона» <b>полностью заменяет</b> расписание на выбранную неделю: все свободные слоты удаляются, создаются заново из шаблона. Занятые слоты не трогаем. Перед применением будет запрос подтверждения.\n\n"
    "<b>Твой шаблон:</b>"
)
TRAINER_SCHEDULE_EMPTY = "Шаблон пуст. Ниже добавь слоты в шаблон или сразу на выбранную неделю."
TRAINER_SCHEDULE_ROW = "{day} {time} — {duration} мин"
TRAINER_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def format_client_group_series_schedule_updated_html(
    *,
    trainer_name: str,
    group_name: str,
    service_name: str,
    arena_name: str | None,
    season_start_date: str | None,
    rules: list[dict],
) -> str:
    """Telegram HTML (client bot): trainer replaced recurring schedule for a training group cohort."""
    tn = html.escape((trainer_name or "").strip() or "Тренер")
    gn = html.escape((group_name or "").strip() or "Группа")
    sn = html.escape((service_name or "").strip() or "—")
    arena_line = ""
    if (arena_name or "").strip():
        arena_line = f"\nПлощадка: <b>{html.escape(arena_name.strip())}</b>"
    season_line = ""
    if (season_start_date or "").strip():
        season_line = f"\nСтарт сезона: <b>{html.escape(season_start_date.strip())}</b>"
    rule_lines: list[str] = []
    for r in rules:
        dow = int(r.get("day_of_week", 0))
        day_short = TRAINER_DAYS[dow] if 0 <= dow <= 6 else "?"
        st_raw = r.get("start_time")
        if st_raw is not None and hasattr(st_raw, "strftime"):
            st = st_raw.strftime("%H:%M")
        else:
            st = str(st_raw or "")[:5]
        dur = int(r.get("duration_minutes") or 60)
        rule_lines.append(f"• {day_short} — <b>{html.escape(st)}</b> ({dur} мин)")
    rules_block = "\n".join(rule_lines) if rule_lines else "—"
    return (
        "📅 <b>Обновлено расписание группового потока</b>\n\n"
        f"Тренер: <b>{tn}</b>\n"
        f"Группа: <b>{gn}</b>\n"
        f"Услуга: {sn}{arena_line}{season_line}\n\n"
        f"<b>Новое расписание:</b>\n{rules_block}\n\n"
        "Актуальные даты смотрите в <b>«Мои записи»</b> или на <b>Главной</b> в боте."
    )


TRAINER_BUTTON_ADD_SLOT = "➕ Добавить слоты вручную на неделю"
TRAINER_SCHEDULE_ADD_TO_TEMPLATE_BUTTON = "В шаблон (для быстрого применения)"
# Short labels for narrow mobile screens (dates appended in code)
TRAINER_BUTTON_APPLY_THIS_WEEK = "▶ Применить шаблон на эту нед."
TRAINER_BUTTON_APPLY_NEXT_WEEK = "▶ Применить шаблон на след. нед."
TRAINER_SCHEDULE_CONFIRM_OVERWRITE = (
    "⚠️ <b>Внимание:</b> это <b>полностью заменит</b> расписание на неделю {start}–{end}.\n\n"
    "Все свободные слоты будут удалены, новые созданы из шаблона. Занятые слоты не трогаем.\n\n"
    "Продолжить?"
)
TRAINER_SCHEDULE_BUTTON_CONFIRM = "Продолжить"
TRAINER_BUTTON_MY_SLOTS = "📋 Моё расписание"
# Text for the main menu button (left of input) when it opens Web App schedule
TRAINER_MENU_SCHEDULE_WEBAPP = "Расписание"
# Short message when /schedule or menu opens Web App (one button below)
TRAINER_SCHEDULE_OPEN_WEBAPP = "📋 Нажми кнопку ниже, чтобы открыть расписание в приложении."
TRAINER_BUTTON_MY_BOOKINGS = "📋 Моё расписание"
TRAINER_BUTTON_BACK = "Назад"
TRAINER_BUTTON_BACK_TO_SCHEDULE = "◀️ Расписание"
TRAINER_BUTTON_BACK_TO_MENU = "◀️ В главное меню"
TRAINER_BUTTON_CLIENTS = "👥 Мои клиенты"
TRAINER_SCHEDULE_CHOOSE_WEEK = "На какую неделю добавляешь слоты?"
TRAINER_SCHEDULE_THIS_WEEK = "Эта неделя ({start}–{end})"
TRAINER_SCHEDULE_NEXT_WEEK = "Следующая неделя ({start}–{end})"
TRAINER_SCHEDULE_CHOOSE_DAY = "Выбери день недели:"
TRAINER_SCHEDULE_CHOOSE_TIME = "Отметь все нужные часы (повторное нажатие снимает отметку), затем «Готово»:"
TRAINER_SCHEDULE_CHOOSE_DURATION = "Длительность занятия (для всех выбранных слотов):"
TRAINER_SCHEDULE_DONE = "Готово ({count})"
TRAINER_SCHEDULE_CANCEL_ADD = "Отмена"
TRAINER_SCHEDULE_SELECT_AT_LEAST_ONE = "Выбери хотя бы один час."
TRAINER_SCHEDULE_BOOKED_SLOT_CANNOT_REMOVE = "Занятой слот нельзя убрать из расписания."
TRAINER_SCHEDULE_ADDED = "Слот добавлен в шаблон."
TRAINER_SCHEDULE_ADDED_MULTI = "В шаблон добавлено слотов: {count}."
TRAINER_SCHEDULE_DAY_CLEARED = "Слоты на этот день в шаблоне убраны."
TRAINER_SCHEDULE_DAY_CLEARED_WEEK = "Слоты на этот день убраны. Добавить слоты на другой день?"
TRAINER_SCHEDULE_TEMPLATE_CHOOSE_ANOTHER_DAY = "Выбери другой день или вернись в расписание."
TRAINER_SCHEDULE_ADDED_TO_WEEK = "На выбранную неделю добавлено слотов: {count}."
TRAINER_SCHEDULE_ADDED_TO_WEEK_MORE = "На неделю добавлено слотов: {count}. Добавить слоты на другой день?"
TRAINER_SCHEDULE_GENERATED = "Расписание на неделю заменено. Создано слотов: {count}. Посмотреть: «Моё расписание»."
TRAINER_SCHEDULE_GENERATED_NONE = "Расписание на неделю заменено. В шаблоне нет слотов на эти дни — неделя очищена от свободных слотов."
TRAINER_SCHEDULE_DELETED = "Слот удалён из шаблона."
TRAINER_BUTTON_CREATE_BOOKING = "➕ Создать запись"
TRAINER_CREATE_BOOKING_NO_SLOTS = (
    "Нет свободных слотов в ближайшие 14 дней (начиная примерно через 2 часа).\n\n"
    "Добавь свободные слоты в расписании и попробуй ещё раз."
)
TRAINER_CREATE_BOOKING_CHOOSE_SLOT = "Выбери свободный слот, на который хочешь записать клиента:"
TRAINER_CREATE_BOOKING_NO_CLIENTS = (
    "Пока в системе нет клиентов, с которыми ты уже проводил занятия.\n\n"
    "Когда появятся первые записи, сможешь быстро записывать их на новые слоты из этого экрана."
)
TRAINER_CREATE_BOOKING_CHOOSE_CLIENT = (
    "Кого записать на <b>{date}</b> ({day}) {time}? Выбери клиента из списка:"
)
TRAINER_CREATE_BOOKING_CHOOSE_TARIFF = (
    "Слот: <b>{date}</b> ({day}) {time}\n"
    "ФИО: <b>{client_name}</b>\n\n"
    "Выбери тариф для записи:"
)
TRAINER_CREATE_BOOKING_DONE = (
    "✅ Записали клиента <b>{client_name}</b> на <b>{date}</b> ({day}) {time}.\n\n"
    "⏰ <b>Напоминания клиенту:</b> {reminder_plan}\n"
    "📩 <b>Подтверждение клиенту:</b> {client_confirmation}\n"
    "📝 <b>Заметка:</b> можно добавить сразу кнопкой ниже."
)
# Appended to TRAINER_CREATE_BOOKING_DONE for onboarding demo (is_sandbox) bookings — same push as real flow.
TRAINER_CREATE_BOOKING_SANDBOX_CANCEL_HINT = (
    "\n\n💡 <i>Чтобы отменить эту запись, откройте «Детали записи» в приложении.</i>"
)
# Rich push is sent by notification_service (trainer_booked loop), not inline from API/bot handlers.
TRAINER_CREATE_BOOKING_CLIENT_CONFIRMATION_QUEUED = (
    "клиент получит подробное уведомление в боте в ближайшее время (услуга, цена, адрес и кнопка «Мои записи»)"
)
TRAINER_BUTTON_ADD_BOOKING_NOTE = "📝 Добавить заметку"
TRAINER_BUTTON_INVITE_CLIENT_TO_BOT = "📣 Пригласить в бота"
TRAINER_ADD_BOOKING_NOTE_PROMPT = (
    "📝 <b>Заметка по занятию</b>\n\n"
    "ФИО: <b>{client_name}</b>\n"
    "Дата занятия: <b>{date}</b> ({day}) {time}\n\n"
    "Пришлите текст заметки одним сообщением — сохраним в хронологии клиента."
)
TRAINER_ADD_BOOKING_NOTE_REQUIRED = "Текст заметки пустой. Пришлите заметку одним сообщением."
TRAINER_ADD_BOOKING_NOTE_SAVED = "✅ Заметка сохранена в карточке клиента."
TRAINER_CREATE_BOOKING_SLOT_UNAVAILABLE = (
    "Слот уже недоступен (кто-то его занял или он был удалён). Обнови расписание и попробуй снова."
)
TRAINER_DATE_FMT = "%d.%m"  # 18.02

# Applied slots (view only)
TRAINER_SLOTS_TITLE = "📋 <b>Применённое расписание</b>\n\nСлоты, в которые клиенты могут записаться:"
TRAINER_SLOTS_THIS_WEEK_HEADER = "\n<b>Эта неделя ({start}–{end})</b>"
TRAINER_SLOTS_NEXT_WEEK_HEADER = "\n<b>Следующая неделя ({start}–{end})</b>"
TRAINER_SLOTS_EMPTY = "Пока нет слотов. Добавь слоты на неделю или примени шаблон в разделе «Расписание»."
TRAINER_BUTTON_OPEN_SCHEDULE_WEBAPP = "📱 Открыть расписание в приложении"
TRAINER_SLOTS_ROW = "{date} {time_range} — {status}"
TRAINER_SLOTS_STATUS_AVAILABLE = "свободен"
TRAINER_SLOTS_STATUS_BOOKED = "занят"
TRAINER_SLOTS_STATUS_CANCELLED = "отменён"
TRAINER_SLOT_DELETED = "Слот удалён."
TRAINER_SLOT_CANNOT_DELETE_BOOKED = "Занятый слот нельзя удалить."

# Trainer: my bookings (list = buttons by day, tap → detail + Write/Cancel)
TRAINER_BOOKINGS_TITLE = "📋 <b>Мои записи</b>"
TRAINER_BOOKINGS_LIST_HINT = "Нажми на запись — откроются детали и кнопки «Написать» / «Отменить»."
TRAINER_BOOKINGS_EMPTY = "Пока нет записей."
TRAINER_BOOKINGS_DAY_EMPTY = "На этот день записей нет."
TRAINER_BOOKINGS_PAGE_BACK = "◀️ Предыдущий день"
TRAINER_BOOKINGS_PAGE_NEXT = "Следующий день ▶️"
TRAINER_BOOKINGS_DAY_HEADER = "\n📅 <b>{date} ({day})</b>"
TRAINER_BOOKINGS_ROW_TIME_CLIENT = "{time} — {client_display}"
TRAINER_BOOKINGS_ROW_EXTRA = "   ({extra})"
TRAINER_BOOKINGS_ROW_COMMENT = "   Комментарий: {comment}"
# Detail screen (one booking): clearer layout
TRAINER_BOOKINGS_DETAIL_HEAD = "📅 <b>{date}</b> ({day})  ·  <b>{time}</b>"
TRAINER_BOOKINGS_DETAIL_CLIENT = "👤 {client_display}"
TRAINER_BOOKINGS_DETAIL_META = "Услуга: {services}  ·  Арена: {arenas}  ·  {session_label}"
TRAINER_BOOKINGS_DETAIL_COMMENT = "💬 Комментарий: {comment}"
TRAINER_BOOKINGS_SESSION_NTH = "{n}-е занятие"
TRAINER_BOOKINGS_BUTTON_WRITE = "✉️ Написать клиенту"
TRAINER_BOOKINGS_BUTTON_WRITE_SLOT = "✉️ Написать клиенту — {date} {time}"
TRAINER_BOOKINGS_BUTTON_CANCEL = "❌ Отменить запись"
TRAINER_BOOKINGS_BUTTON_CONFIRM = "✅ Подтвердить"
# Client cancelled their booking (sent to trainer immediately)
TRAINER_BOOKING_CANCELLED_CATALOG_LINE = (
    "🌐 <b>Онлайн-запись:</b> это окно снова в каталоге — его могут взять другие клиенты. "
    "Чтобы пригласить своих, нажмите кнопку ниже."
)
TRAINER_BOOKING_CANCELLED_BY_CLIENT = (
    "🗑️ <b>Запись отменена клиентом</b>\n\n"
    "👤 <b>ФИО:</b> {client_name}\n"
    "📅 <b>Было:</b> {date} ({day}) · {time}\n"
    "💬 <b>Причина:</b> {reason}\n\n"
    f"{TRAINER_BOOKING_CANCELLED_CATALOG_LINE}\n\n"
    "Связаться с клиентом или открыть рассылку — кнопки ниже."
)
TRAINER_BOOKING_CANCELLED_BY_CLIENT_NO_REASON = (
    "🗑️ <b>Запись отменена клиентом</b>\n\n"
    "👤 <b>ФИО:</b> {client_name}\n"
    "📅 <b>Было:</b> {date} ({day}) · {time}\n\n"
    f"{TRAINER_BOOKING_CANCELLED_CATALOG_LINE}\n\n"
    "Связаться с клиентом или открыть рассылку — кнопки ниже."
)
TRAINER_BUTTON_CANCEL_CLIENT_WRITE = "💬 Написать клиенту"
TRAINER_BUTTON_CANCEL_CLIENT_SCHEDULE = "📅 Расписание и слоты"
TRAINER_BUTTON_OFFER_FREED_SLOT_TO_CLIENTS = "📣 Предложить это окно своим"
TRAINER_BUTTON_SUPPORT_GO_SUBSCRIPTION = "Перейти в «Подписку»"
TRAINER_BOOKINGS_BUTTON_DECLINE = "❌ Отклонить"
TRAINER_BOOKINGS_BUTTON_MAKE_REGULAR = "📅 Сделать постоянным клиентом"
TRAINER_BOOKINGS_BUTTON_REMOVE_REGULARITY = "📅 Снять регулярность"
TRAINER_RECURRING_DONE = "Клиент закреплён как постоянный: каждую неделю в это время слот будет автоматически бронироваться за ним."
TRAINER_RECURRING_REMOVED = "Регулярность снята."
TRAINER_RECURRING_NEEDS_SERVICE = (
    "Не удалось закрепить: в профиле нет ни одной услуги. Добавьте услугу в каталоге — автозапись привязывается к ней."
)
TRAINER_RECURRING_MATERIALIZE_INCOMPLETE = (
    "Не удалось создать все будущие записи: часть окон в расписании занята или пересекается с другим слотом. "
    "Освободите время и попробуйте снова."
)
TRAINER_BOOKINGS_CHOOSE_WRITE = "Выбери запись, чтобы написать клиенту:"
TRAINER_BOOKINGS_CHOOSE_CANCEL = "Какую запись отменить? Перед отменой предупреди клиента."
TRAINER_BOOKINGS_WRITE_LINK = "Запись {date} {time}. Написать клиенту в Telegram?"
TRAINER_BOOKINGS_BUTTON_BACK_TO_LIST = "◀️ К списку записей"
TRAINER_BOOKINGS_CANCEL_WARNING = (
    "⚠️ <b>Перед отменой обязательно предупреди клиента</b> (звонок или сообщение в Telegram).\n\n"
    "Отменить запись на <b>{date} ({day}) {time}</b>?"
)
TRAINER_BOOKINGS_CANCEL_CONFIRM_YES = "Да, отменить"
TRAINER_BOOKINGS_CANCEL_CONFIRM_NO = "Нет, вернуться"
TRAINER_BOOKINGS_CANCELLED = "Запись отменена. Слот снова свободен."
TRAINER_BOOKINGS_BUTTON_WRITE_LINK = "✉️ Написать в Telegram"
# Prefix for the first trainer_bot push about a client-initiated pending booking (HTML).
TRAINER_FIRST_ONLINE_BOOKING_NOTIFICATION_PREFIX = (
    "✨ <b>Первая онлайн-запись</b> — клиент записался сам, подтвердите ниже.\n\n"
)
TRAINER_BOOKING_NOTIFICATION = (
    "🔔 <b>Новая запись</b> — нужно ваше решение\n\n"
    "👤 <b>ФИО:</b> {client_name}\n"
    "📞 {phone}\n"
    "📅 <b>{date} ({day}) {time}</b> — {duration} мин.\n"
    "🎯 {service}\n"
    "💳 <b>Тариф:</b> {tariff}\n"
    "📍 {city} · 🏟 {arenas}\n"
    "💬 <b>Комментарий:</b> {comment}\n\n"
    "<b>Действия:</b> подтвердите, отклоните или напишите клиенту — кнопки ниже.\n\n"
    "<i>Слот занят; клиент получит напоминания автоматически.</i>"
)
TRAINER_BOOKING_NOTIFICATION_NO_COMMENT = (
    "🔔 <b>Новая запись</b> — нужно ваше решение\n\n"
    "👤 <b>ФИО:</b> {client_name}\n"
    "📞 {phone}\n"
    "📅 <b>{date} ({day}) {time}</b> — {duration} мин.\n"
    "🎯 {service}\n"
    "💳 <b>Тариф:</b> {tariff}\n"
    "📍 {city} · 🏟 {arenas}\n\n"
    "<b>Действия:</b> подтвердите, отклоните или напишите клиенту — кнопки ниже.\n\n"
    "<i>Слот занят; клиент получит напоминания автоматически.</i>"
)
TRAINER_BOOKING_CONFIRMED_BTN_DETAILS = "🔍 Посмотреть детали"
TRAINER_BOOKING_CONFIRMED_BTN_WRITE = "📩 Написать клиенту"


def format_trainer_booking_confirmed_echo_html(
    *,
    client_name: str,
    client_phone: str | None,
    date: str,
    day: str,
    time: str,
    duration_minutes: int | None,
    service_name: str | None,
    booking_price_cents: int | None,
    price_tier_label: str | None,
    arena_name: str | None,
    arena_address: str | None,
) -> str:
    """Echo in trainer chat after confirming a booking (HTML; escape plain-text inputs before call)."""
    cn = html.escape((client_name or "").strip() or "Клиент")
    cp = (client_phone or "").strip()
    if cp:
        client_line = f"👤 <b>ФИО:</b> {cn} (<b>{html.escape(cp)}</b>)\n"
    else:
        client_line = f"👤 <b>ФИО:</b> {cn}\n"
    ds = html.escape(date)
    dy = html.escape(day)
    ts = html.escape(time)
    dur = int(duration_minutes) if duration_minutes is not None else None
    dur_part = f" – {dur} мин." if dur and dur > 0 else ""
    when_line = f"📅 <b>{ds} ({dy}) {ts}</b>{dur_part}\n"
    svc_lines: list[str] = []
    svc = (service_name or "").strip()
    if svc:
        if (price_tier_label or "").strip():
            svc_lines.append(
                f"🎯 <b>{html.escape(svc)}</b> · {html.escape(price_tier_label.strip())}"
            )
        else:
            svc_lines.append(f"🎯 <b>{html.escape(svc)}</b>")
    elif (price_tier_label or "").strip():
        svc_lines.append(f"🎯 {html.escape(price_tier_label.strip())}")
    if booking_price_cents is not None:
        byn = booking_price_cents / 100.0
        ps = format_rubles_byn_display(byn)
        svc_lines.append(f"💳 <b>{html.escape(ps)}</b>")
    service_block = ("\n".join(svc_lines) + "\n") if svc_lines else ""
    an = (arena_name or "").strip()
    aa = (arena_address or "").strip()
    if an and aa:
        venue = f"📍 <b>{html.escape(an)}</b>\n{html.escape(aa)}\n"
    elif an:
        venue = f"📍 <b>{html.escape(an)}</b>\n"
    elif aa:
        venue = f"📍 {html.escape(aa)}\n"
    else:
        venue = ""
    return (
        "✅ <b>Запись подтверждена!</b>\n\n"
        f"{client_line}"
        f"{when_line}"
        f"{service_block}"
        f"{venue}"
    )


def build_trainer_booking_confirmed_echo_reply_markup(
    *,
    webapp_base: str,
    booking_id: int,
    client_id: int | None = None,
    client_telegram_id: int | None = None,
    trainer_has_crm: bool = False,
):
    """WebApp slot detail + write client (CRM WebApp relay/DM) or tg:// fallback."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (webapp_base or "").rstrip("/")
    rows: list[list[InlineKeyboardButton]] = []
    https = base.lower().startswith("https://")
    if https:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BOOKING_CONFIRMED_BTN_DETAILS,
                    web_app=WebAppInfo(
                        url=f"{base}/webapp/schedule-editor?open_booking={int(booking_id)}"
                    ),
                ),
            ]
        )
    if trainer_has_crm and client_id is not None and https:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                    web_app=WebAppInfo(
                        url=(
                            f"{base}/webapp/trainer-clients?"
                            f"client_id={int(client_id)}&open_write=1"
                        )
                    ),
                ),
            ]
        )
    elif client_telegram_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                    url=f"tg://user?id={int(client_telegram_id)}",
                ),
            ]
        )
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_HTML = (
    "<i>Дальше — рутина на автопилоте: напоминания, история клиента и расписание в одном месте. "
    "Вы уже сделали главное. 🚀</i>"
)
TRAINER_FIRST_BOOKING_NO_TG_NUDGE_HTML = (
    "✨ <b>Клиент ещё не в Telegram-боте</b> — нажмите «Пригласить в бота», и он сможет получать напоминания и "
    "подтверждения в мессенджере (пока достаточно звонка или SMS)."
)
TRAINER_FIRST_BOOKING_TG_OK_LINE_HTML = (
    "✅ Клиент в боте — напоминания и подтверждение уйдут автоматически."
)


def _milestone_service_tariff_price_html(
    service_name: str | None,
    price_tier_label: str | None,
    booking_price_cents: int | None,
) -> str:
    """Inner HTML lines for service / tariff / price (ParseMode.HTML safe)."""
    lines: list[str] = []
    svc = (service_name or "").strip()
    if svc:
        if (price_tier_label or "").strip():
            tl = html.escape(price_tier_label.strip())
            lines.append(f"<b>{html.escape(svc)}</b> ({tl})")
        else:
            lines.append(f"<b>{html.escape(svc)}</b>")
    elif (price_tier_label or "").strip():
        lines.append(f"Тариф: <b>{html.escape(price_tier_label.strip())}</b>")
    if booking_price_cents is not None:
        byn = booking_price_cents / 100.0
        ps = format_rubles_byn_display(byn)
        lines.append(f"💰 <b>Цена:</b> {html.escape(ps)}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def format_trainer_first_booking_milestone_rich_html(
    *,
    client_name: str,
    client_phone: str,
    date_str: str,
    day_label: str,
    time_str: str,
    arena_name: str | None,
    arena_address: str | None,
    service_name: str | None,
    price_tier_label: str | None,
    booking_price_cents: int | None,
    arena_city_name: str | None = None,
    duration_minutes: int | None = None,
    map_link: str | None = None,
    client_comment: str | None = None,
    client_has_telegram: bool | None = None,
    sandbox_demo_identity: bool = False,
) -> str:
    """
    Rich «первая запись» card for trainer bot (HTML). Escapes user-controlled fields.

    When ``sandbox_demo_identity`` is True (sandbox booking **and** sandbox client row), the Telegram
    invite/teaser paragraph is omitted — there's nothing real to invite.
    """
    cn = html.escape((client_name or "").strip() or "Клиент")
    phone = (client_phone or "").strip()
    phone_line = f"📞 <b>Телефон:</b> {html.escape(phone)}\n" if phone else ""

    city = (arena_city_name or "").strip()
    an = (arena_name or "").strip()
    aa = (arena_address or "").strip()
    city_line = ""
    if city:
        city_line = f"🏙 <b>Город:</b> {html.escape(city)}\n"
    if an or aa:
        venue_body = ""
        if an:
            venue_body += f"<b>{html.escape(an)}</b>\n"
        if aa:
            venue_body += f"{html.escape(aa)}\n"
        venue_block = f"📍 <b>Площадка</b>\n{city_line}{venue_body}".rstrip("\n")
    else:
        fallback_city = f"{city_line}" if city_line else ""
        venue_block = (
            "📍 <b>Площадка</b>\n"
            f"{fallback_city}"
            "<i>Арена не привязана к слоту — уточните у клиента или в расписании.</i>"
        ).rstrip("\n")

    svc_block = _milestone_service_tariff_price_html(service_name, price_tier_label, booking_price_cents)
    service_section = ""
    if svc_block.strip():
        service_section = f"🎯 <b>Услуга и оплата</b>\n{svc_block}"

    dur = int(duration_minutes) if duration_minutes is not None else None
    dur_suffix = f" · {dur} мин" if dur and dur > 0 else ""
    when_line = f"{html.escape(date_str)} ({html.escape(day_label)}) · {html.escape(time_str)}{dur_suffix}"

    map_section = ""
    ml = (map_link or "").strip()
    if ml:
        esc = html.escape(ml, quote=True)
        map_section = f"🗺 <b>Карта:</b> <a href=\"{esc}\">открыть в Яндекс.Картах</a>"

    comment_raw = (client_comment or "").strip()
    comment_section = ""
    if comment_raw:
        comment_section = f"💬 <b>Комментарий клиента</b>\n{html.escape(truncate_text(comment_raw, 400))}"

    # Demo onboarding booking + phantom client: skip «Пригласить в бота» copy — no real Telegram invite target.
    tg_line = ""
    if not sandbox_demo_identity:
        if client_has_telegram is True:
            tg_line = TRAINER_FIRST_BOOKING_TG_OK_LINE_HTML
        elif client_has_telegram is False:
            tg_line = TRAINER_FIRST_BOOKING_NO_TG_NUDGE_HTML

    blocks: list[str] = [
        "🎉 <b>Старт засчитан: это ваша первая запись в Ice Pro!</b>\n\n"
        "Вы только что перевели занятие в понятный план — с датой, местом и контекстом.",
        f"👤 <b>ФИО:</b> {cn}\n" + phone_line.rstrip("\n"),
        venue_block,
        f"📅 <b>Время</b>\n{when_line}",
    ]
    if service_section:
        blocks.append(service_section.rstrip("\n"))
    if map_section:
        blocks.append(map_section)
    if comment_section:
        blocks.append(comment_section)
    if tg_line:
        blocks.append(tg_line)
    blocks.append(TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_HTML)
    return "\n\n".join(blocks)


def build_trainer_first_booking_milestone_reply_markup(
    *,
    webapp_base: str,
    booking_id: int,
    client_id: int | None = None,
    client_telegram_id: int | None = None,
    trainer_has_crm: bool = False,
    is_sandbox: bool = False,
):
    """
    Inline keyboard for the first-booking celebration (must match trainer bot callback prefixes).

    Sandbox milestone: same celebration text and details button, but the «Написать клиенту» and
    «Пригласить в бот» buttons are dropped — the demo identity has no real Telegram account.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    # Keep in sync with trainer_handlers / webapp route push (same callback_data strings).
    booking_add_note_prefix = "booking_add_note:"
    booking_invite_prefix = "booking_invite_client:"
    rows: list[list[InlineKeyboardButton]] = []
    base = (webapp_base or "").rstrip("/")
    https = base.lower().startswith("https://")
    if https:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BOOKING_CONFIRMED_BTN_DETAILS,
                    web_app=WebAppInfo(
                        url=f"{base}/webapp/schedule-editor?open_booking={int(booking_id)}"
                    ),
                ),
            ]
        )
    if not is_sandbox and trainer_has_crm and client_id is not None and https:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                    web_app=WebAppInfo(
                        url=(
                            f"{base}/webapp/trainer-clients?"
                            f"client_id={int(client_id)}&open_write=1"
                        )
                    ),
                ),
            ]
        )
    elif client_telegram_id and not is_sandbox:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BOOKING_CONFIRMED_BTN_WRITE,
                    url=f"tg://user?id={int(client_telegram_id)}",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=TRAINER_BUTTON_ADD_BOOKING_NOTE,
                callback_data=f"{booking_add_note_prefix}{int(booking_id)}",
            ),
        ]
    )
    if not client_telegram_id and not is_sandbox:
        rows.append(
            [
                InlineKeyboardButton(
                    text=TRAINER_BUTTON_INVITE_CLIENT_TO_BOT,
                    callback_data=f"{booking_invite_prefix}{int(booking_id)}",
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _trainer_slot_time_hhmm(t: object) -> str:
    if t is None:
        return "—"
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    s = str(t).strip()
    return s[:5] if len(s) >= 5 else (s or "—")


def format_trainer_first_booking_milestone_from_booking_row(info: dict) -> str:
    """HTML card from `get_booking_milestone_display_for_trainer` / `confirm_booking` payload dict."""
    d = info.get("slot_date")
    st = info.get("start_time")
    date_str = d.strftime("%d.%m") if d and hasattr(d, "strftime") else "—"
    day_str = TRAINER_DAYS[d.weekday()] if d and hasattr(d, "weekday") else ""
    time_str = _trainer_slot_time_hhmm(st)
    raw_tid = info.get("client_telegram_id")
    has_tg = bool(raw_tid)
    sandbox_demo = bool(info.get("is_sandbox")) and bool(info.get("client_is_sandbox"))
    return format_trainer_first_booking_milestone_rich_html(
        client_name=(info.get("client_name") or "").strip() or "Клиент",
        client_phone=(info.get("client_phone") or "").strip(),
        date_str=date_str,
        day_label=day_str,
        time_str=time_str,
        arena_name=info.get("arena_name"),
        arena_address=info.get("arena_address"),
        service_name=info.get("service_name"),
        price_tier_label=info.get("price_tier_label"),
        booking_price_cents=info.get("booking_price_cents"),
        arena_city_name=info.get("arena_city_name"),
        duration_minutes=info.get("duration_minutes"),
        map_link=info.get("map_link"),
        client_comment=info.get("client_comment"),
        client_has_telegram=has_tg,
        sandbox_demo_identity=sandbox_demo,
    )


TRAINER_SHARE_FIRST_BOOKING_ACTIVE_HIDDEN_FROM_CATALOG_HTML = (
    "👁 <b>Профиль активен, но вы скрыты из каталога</b>\n\n"
    "В приложении в профиле включите <b>«Показать в каталоге»</b> — иначе клиенты не увидят вас в общем списке.\n\n"
    "Ссылки для записи:\n\n"
    "1️⃣ <b>Персональная ссылка в бота</b> (на вас и услугу):\n<code>{deep_link}</code>\n\n"
    "2️⃣ <b>Страница каталога:</b>\n<code>{catalog_url}</code>"
)
TRAINER_SHARE_CATALOG_TIP_BOTH_HTML = (
    "📣 <b>Следующий шаг к новым клиентам</b>\n\n"
    "Чтобы клиенты записывались к вам сами, поделитесь ссылками:\n\n"
    "1️⃣ <b>Персональная ссылка в бота</b> (на вас и услугу):\n<code>{deep_link}</code>\n\n"
    "2️⃣ <b>Страница каталога:</b>\n<code>{catalog_url}</code>"
)
TRAINER_SHARE_CATALOG_TIP_DEEP_ONLY_HTML = (
    "📣 <b>Следующий шаг к новым клиентам</b>\n\n"
    "Поделитесь персональной ссылкой на запись к вам:\n\n"
    "<code>{deep_link}</code>"
)
TRAINER_SHARE_CATALOG_TIP_NO_CLIENT_BOT = (
    "📣 <b>Следующий шаг</b>\n\n"
    "Попросите администратора указать <b>имя клиентского бота</b> в настройках — "
    "тогда здесь появится готовая ссылка для клиентов."
)
TRAINER_CLIENT_INVITE_LINK_FOR_TRAINER = (
    "📣 <b>Ссылка для клиента {client_name}</b>\n\n"
    "Перешлите это сообщение клиенту или скопируйте ссылку: так он сможет привязать свой Telegram к уже созданной записи и получать уведомления.\n\n"
    "<code>{deep_link}</code>\n\n"
    "<i>Действует 14 дней.</i>"
)
TRAINER_SHARE_CATALOG_TIP_PROFILE_INCOMPLETE = (
    "📣 <b>Следующий шаг</b>\n\n"
    "В профиле укажите <b>город и услугу</b> — тогда мы соберём для вас готовую ссылку на запись и на каталог."
)
TRAINER_BOOKING_DECLINE_PROMPT = (
    "Напиши короткий комментарий, почему не получается провести это занятие.\n\n"
    "Комментарий <b>обязателен</b> — клиент увидит его в уведомлении об отказе."
)
TRAINER_BOOKING_DECLINE_COMMENT_REQUIRED = (
    "Комментарий обязателен. Напиши причину отклонения для клиента (пустое сообщение не подойдёт)."
)
TRAINER_BOOKING_DECLINED_DONE = "Запись отклонена, клиенту отправлено сообщение с причиной."
TRAINER_BOOKING_CONFIRM_REMINDER = (
    "⏰ <b>Скоро: нужно решение по записи</b>\n\n"
    "Слот начинается менее чем через <b>2 часа</b>.\n"
    "👤 <b>ФИО:</b> {client_display}\n"
    "📅 <b>{date} ({day}) {time}</b>\n\n"
    "Подтвердите или отклоните запись — чтобы клиент был в курсе."
)

# Trainer: /stats — statistics for subscription value
TRAINER_STATS_TITLE = "📊 <b>Статистика</b>\n\n"
TRAINER_STATS_WEEK = (
    "📅 <b>Эта неделя</b> ({week_start}–{week_end})\n"
    "Занятий: {week_total} (проведено {week_completed}, предстоит {week_upcoming})\n\n"
)
TRAINER_STATS_MONTH = "📆 <b>Этот месяц</b>\nЗанятий: {month_total}\n\n"
TRAINER_STATS_LOAD = (
    "📈 <b>Загрузка</b> (эта неделя)\n"
    "Слотов в расписании: {week_slots_total}, занято: {week_slots_booked} ({load_pct}%)\n\n"
)
TRAINER_STATS_LOAD_EMPTY = "📈 <b>Загрузка</b> (эта неделя)\nНет слотов в расписании на эту неделю.\n\n"
TRAINER_STATS_NEW_CLIENTS = "👤 <b>Новые клиенты</b> (за 30 дней): {new_clients_30d}\n\n"
TRAINER_STATS_RATING = "⭐ <b>Рейтинг</b>: {rating_avg} из 5 ({rating_count} отзывов)"
TRAINER_STATS_RATING_NONE = "⭐ <b>Рейтинг</b>: пока нет оценок"
TRAINER_STATS_PASSES = "📦 <b>Абонементы</b>: активно {passes_active} (выдано за 30 дн.: {passes_issued_30d})"
TRAINER_STATS_CERTS = (
    "🎁 <b>Сертификаты</b>: выдано {certificates_issued_total}, с остатком {certificates_with_balance} "
    "(на сумму {certificate_balance_byn} " + BYR_SIGN + "), погашено за 30 дн.: {certificates_redeemed_30d}"
)
TRAINER_STATS_OPEN_APP = "📊 Открой статистику в приложении — графики, тренды и инсайты по работе."
TRAINER_BUTTON_STATS_APP = "📊 Открыть статистику"
TRAINER_CLIENT_FAVORITE_ADDED_HTML = (
    "💛 <b>Приятный знак внимания</b>\n\n"
    "<b>{client_label}</b> добавил(а) вас в <b>избранное</b> в каталоге — так отмечают профиль, "
    "который не хочется терять из виду.\n\n"
    "До первой записи дойдёт не каждый, а вы уже зацепили интерес — "
    "маленькая победа, которую приятно заметить 🙌"
)
TRAINER_BUTTON_FAVORITE_STATS_WEBAPP = "Статистика"
TRAINER_SUBSCRIPTION_REMINDER = (
    "💳 <b>Подписка заканчивается {expires_date}</b>\n\n"
    "Продлите тариф — снова откроются расписание, база клиентов и онлайн-запись. "
    "<b>Карточка в каталоге остаётся</b>: вас по-прежнему видно в списке."
)
TRAINER_SUBSCRIPTION_REMINDER_TRIAL = (
    "⏳ <b>Завтра пробный период закончится</b> ({expires_date})\n\n"
    "Профиль остаётся в каталоге — клиенты по-прежнему вас находят 🧭\n\n"
    "Но завтра <b>встанет на паузу</b>:\n"
    "• онлайн-запись через каталог\n"
    "• CRM перейдёт в режим только для чтения\n"
    "• новые клиенты не смогут записаться автоматически\n\n"
    "Продлить и сохранить контроль 👇"
)


def _money_byn(cents: int | None) -> str:
    return format_kopeks_byn_display(int(cents or 0))


def _ru_word(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if 11 <= (n % 100) <= 14:
        return many
    m = n % 10
    if m == 1:
        return one
    if m in (2, 3, 4):
        return few
    return many


def format_trainer_trial_roi_recap_html(
    *,
    recap,
    expires_date: str,
    days_until_expiry: int = 2,
) -> str:
    """
    D-2 message: pure mental anchoring — facts about real value already received, no CTA.
    Tone: «ты уже получил пользу», not «купи». Decision is asked on D-1, not here.
    ``recap`` is TrialRoiRecap-like; kept duck-typed to avoid importing app-layer objects here.
    """
    fact_lines: list[str] = []
    if recap.completed_sessions_count > 0:
        fact_lines.append(
            f"• провести <b>{recap.completed_sessions_count}</b> "
            f"{_ru_word(recap.completed_sessions_count, 'тренировку', 'тренировки', 'тренировок')} без хаоса в расписании"
        )
    if recap.self_bookings_count > 0:
        fact_lines.append(
            f"• заранее подтвердить <b>{recap.self_bookings_count}</b> "
            f"{_ru_word(recap.self_bookings_count, 'запись', 'записи', 'записей')} без переписки «когда удобно?»"
        )
    if recap.repeat_bookings_count > 0:
        fact_lines.append(
            f"• не потерять <b>{recap.repeat_bookings_count}</b> "
            f"{_ru_word(recap.repeat_bookings_count, 'повторную запись', 'повторные записи', 'повторных записей')}"
        )
    if recap.future_available_slots_count > 0:
        fact_lines.append(
            f"• заранее видеть в календаре <b>{recap.future_available_slots_count}</b> "
            f"{_ru_word(recap.future_available_slots_count, 'свободное окно', 'свободных окна', 'свободных окон')}"
        )
    if recap.auto_reminders_sent_count > 0:
        fact_lines.append(
            f"• отправить <b>{recap.auto_reminders_sent_count}</b> "
            f"{_ru_word(recap.auto_reminders_sent_count, 'напоминание', 'напоминания', 'напоминаний')} клиентам — автоматически"
        )
    accounting_count = int(recap.pass_redemptions_count or 0) + int(recap.certificate_credits_count or 0)
    if accounting_count > 0:
        fact_lines.append(
            f"• учесть <b>{accounting_count}</b> "
            f"{_ru_word(accounting_count, 'списание', 'списания', 'списаний')} по абонементам/сертификатам без ручных заметок"
        )
    if not fact_lines:
        fact_lines.append("• держать расписание, клиентов и оплату в одном месте — без отдельной таблицы и переписок по кускам")

    saved_line = ""
    if recap.saved_minutes_display > 0:
        saved_line = (
            f"\n\n⏱ ≈ <b>{recap.saved_minutes_display} "
            f"{_ru_word(recap.saved_minutes_display, 'минута', 'минуты', 'минут')} рутины снято</b> "
            "за счёт записей, напоминаний, подтверждений и учёта."
        )

    has_revenue = recap.revenue_total_cents > 0
    revenue_block = ""
    if has_revenue:
        revenue_block = (
            "\n\n💼 <b>Деньги, которые уже прошли через систему:</b>\n"
            f"• Разовые занятия: <b>{_money_byn(recap.revenue_sessions_cents)}</b>\n"
            f"• Абонементы: <b>{_money_byn(recap.revenue_pass_sales_cents)}</b>\n"
            f"• Сертификаты: <b>{_money_byn(recap.revenue_certificate_sales_cents)}</b>\n"
            f"Итого в учёте: <b>{_money_byn(recap.revenue_total_cents)}</b>"
        )

    days_n = max(1, int(days_until_expiry))
    days_phrase = (
        f"<b>{days_n} {_ru_word(days_n, 'день', 'дня', 'дней')}</b>"
    )

    # Mental anchoring close: state the fact about expiry, but reassure that the catalog presence stays.
    # We deliberately do NOT add "продлить →"-style CTA here; D-1 message owns the decision ask.
    return (
        "📊 <b>Короткая сводка по пробному периоду</b>\n\n"
        "За это время платформа уже помогла:\n"
        + "\n".join(fact_lines)
        + saved_line
        + revenue_block
        + "\n\n"
        f"Через {days_phrase} trial закончится — но <b>профиль останется в каталоге</b>, "
        "клиенты по-прежнему смогут вас находить 🧭\n\n"
        f"<i>Trial действует до {html.escape(expires_date)}.</i>"
    )


# Напоминание об окончании подписки / триала: одна кнопка → мини-приложение trainer-subscription (тарифы и оплата).
TRAINER_SUBSCRIPTION_PUSH_BTN_WEBAPP = "💳 Тарифы и оплата"
TRAINER_BUTTON_PAY_SUBSCRIPTION = "Продлить подписку"
TRAINER_BUTTON_CHOOSE_TARIFF = "Выбрать тариф"
# /subscription — мини-апп trainer-subscription
TRAINER_BUTTON_SUBSCRIPTION_CONSTRUCTOR = "Подписки"
TRAINER_SUBSCRIPTION_WITH_TIER = (
    "📋 Тариф: <b>{tier_name}</b>\n"
    "До <b>{expires_date}</b>"
)
TRAINER_SUBSCRIPTION_WITHOUT_TIER = (
    "📋 <b>Сейчас без активного тарифа</b>\n\n"
    "Расписание и клиентская база на паузе. <b>Карточка в общем каталоге остаётся</b> — вас можно найти в списке. "
    "Чтобы вернуть ведение записей и онлайн-запись, выберите тариф ниже — в своём темпе."
)
TRAINER_SUBSCRIPTION_ACTIVE = (
    "Подписка на платформу активна до <b>{expires_date}</b>. Ты в каталоге.\n\n"
    "Кнопка ниже — оплата за <b>следующий период</b> (после этой даты). Можно выбрать срок: месяц, 3 мес, год или 1,5 года."
)
TRAINER_SUBSCRIPTION_EXPIRED = (
    "Срок подписки прошёл. Оформите новый период — вернутся расписание, база и онлайн-запись. "
    "<b>В каталоге карточка остаётся видимой.</b>"
)

# Одноразовое уведомление в боте сразу после перевода подписки в past_due (см. notification_loops).
TRAINER_SUBSCRIPTION_JUST_EXPIRED_TRIAL = (
    "Пробный период завершился — спасибо, что попробовали сервис.\n\n"
    "Платные функции сейчас на паузе, но <b>карточка в каталоге остаётся</b>: вас можно найти в списке. "
    "Когда будете готовы, откройте тарифы — расписание и клиенты снова под рукой, без спешки."
)
TRAINER_SUBSCRIPTION_JUST_EXPIRED_PAID = (
    "Оплаченный период закончился.\n\n"
    "<b>Карточка в каталоге остаётся на виду</b>. Расписание, база и онлайн-запись снова заработают после продления — "
    "ниже кнопка «Тарифы и оплата»."
)

# ---------------------------------------------------------------------------
# Lead Mode recovery series (D+0 / D+3 / D+14 / D+30) — see lead_mode_recovery_use_cases.
# Tone: "ты остался в системе как supply, без paid-control" — never "тебя отключили".
# All messages may inject a loss-framing line using real demand numbers (see _format_signals_line).
# ---------------------------------------------------------------------------

# D+0: graceful downgrade, not punishment. State plainly what stays and what is paused —
# trainer should read this as «я перешёл в более лёгкий режим», not «меня отключили».
TRAINER_LEAD_MODE_RECOVERY_D0_TRIAL = (
    "🎯 <b>Пробный период закончился</b>\n\n"
    "Ваш профиль <b>всё ещё активен в каталоге</b> — клиенты могут вас находить и писать в Telegram 🧭\n\n"
    "Сейчас <b>на паузе</b>:\n"
    "• онлайн-запись через каталог\n"
    "• CRM и автоматизация\n"
    "• новые записи через систему\n\n"
    "Вернуть рабочий режим — кнопка ниже 👇"
)
TRAINER_LEAD_MODE_RECOVERY_D0_PAID = (
    "💼 Оплаченный период закончился — <b>спасибо, что были с нами</b>.\n\n"
    "<b>Что остаётся без доплаты:</b>\n"
    "• 🧭 Профиль в каталоге — вас по-прежнему находят\n"
    "• 📊 Короткая сводка интереса к карточке в мини-приложении\n\n"
    "📌 <b>На паузе</b> — онлайн-запись, календарь и CRM. "
    "Текущие записи и абонементы <b>не ломаем</b> — всё доживает как обычно.\n\n"
    "Продлить и вернуть привычный ритм — кнопка ниже 👇"
)

# D+3: gentle reminder. Soft loss framing — "пока спрос идёт, но без CRM это просто просмотры".
TRAINER_LEAD_MODE_RECOVERY_D3 = (
    "Прошло несколько дней без подписки.\n\n"
    "{signals_line}"
    "Эти люди уже видят вашу карточку, но <b>записаться онлайн</b> не могут — пока подписка не активна. "
    "Вернуть приём заявок в один клик 👇"
)

# D+14: stronger loss framing. Now we have two weeks of real demand to point at.
TRAINER_LEAD_MODE_RECOVERY_D14 = (
    "Две недели без активной подписки.\n\n"
    "{signals_line}"
    "Каждый из этих просмотров — потенциальная запись, которая <b>не дошла до календаря</b>. "
    "С активной подпиской клиенты записываются сами, а вы видите их в один экран.\n\n"
    "Самое время вернуть онлайн-запись 👇"
)

# D+30: last call. Honest framing — мы не давим, просто говорим как есть.
TRAINER_LEAD_MODE_RECOVERY_D30 = (
    "Месяц без подписки. Карточка по-прежнему в каталоге — мы вас не убираем.\n\n"
    "{signals_line}"
    "Если решите вернуться — расписание, база клиентов и онлайн-запись восстановятся в полном объёме сразу. "
    "Ничего не потеряется.\n\n"
    "Если пока не до этого — карточка остаётся, ничего делать не нужно."
)

# Loss-framing line builder. Used by notification_loops to inject real numbers into D+3/D+14/D+30.
# Three variants by signal density — keeps the message honest (no "23 просмотра" if it's actually 0).
TRAINER_LEAD_MODE_SIGNALS_BOTH = (
    "За это время <b>{views} просмотров карточки</b> и <b>{clicks} переходов в Telegram</b>. "
)
TRAINER_LEAD_MODE_SIGNALS_VIEWS_ONLY = (
    "За это время вашу карточку посмотрели <b>{views} раз</b>. "
)
TRAINER_LEAD_MODE_SIGNALS_FAVORITES = (
    "Вас <b>{favorites} раз</b> добавили в <b>избранное</b> в каталоге. "
)
TRAINER_LEAD_MODE_SIGNALS_NONE = ""  # Empty — message reads naturally without the signals sentence.

# Subscription tier access messages
TRAINER_TIER_REQUIRED_CRM = (
    "⚠️ Для этой функции нужен активный тариф <b>CRM</b> или выше.\n\n"
    "Оформите подписку — откроются расписание, клиентская база, абонементы и сертификаты. "
    "<b>Карточка в общем каталоге при этом остаётся</b>, чтобы клиенты вас находили."
)
TRAINER_TIER_REQUIRED_ONLINE = (
    "⚠️ Для онлайн-записи клиентов нужна подписка уровня <b>Онлайн-запись</b> или выше.\n\n"
    "С этим уровнем клиенты смогут записываться к тебе через каталог самостоятельно."
)
TRAINER_TIER_REQUIRED_ANALYTICS = (
    "⚠️ Для аналитики нужна подписка уровня <b>Аналитика</b>.\n\n"
    "С этим уровнем тебе доступны отчёты, статистика и выгрузка данных."
)
TRAINER_TIER_CTA = "Оформи подписку в разделе ниже 👇"
TRAINER_BUTTON_SUBSCRIPTION_TIERS = "💳 Выбрать тариф"

TRAINER_BUTTON_PASSES = "📦 Абонементы/Сертификаты"

# Admin: /stats — platform overview (current + 7d + 30d + signals)
ADMIN_STATS_TITLE = "📊 <b>Статистика платформы</b>\n\n"
ADMIN_STATS_SECTION_NORTH_STAR = "🎯 <b>North Star</b> — подтверждённые записи за неделю слота\n{lines}\n"
ADMIN_STATS_NORTH_STAR_CURRENT = "• Эта неделя ({d0}—{d1}): <b>{n}</b>"
ADMIN_STATS_NORTH_STAR_PREV = "• Прошлая неделя: <b>{n}</b>"
ADMIN_STATS_SECTION_ACTIVATION = "🪜 <b>Активация тренеров</b>\n{lines}\n"
ADMIN_STATS_ACTIVATION_STAGE = "• {label}: {n}"
ADMIN_STATS_ACTIVATION_HINT = "<i>Подробный список по тренерам — в мини-приложении «Панель админа».</i>"
ADMIN_STATS_SECTION_NOW = "🟢 <b>Сейчас</b>\n{lines}\n"
ADMIN_STATS_SECTION_7D = "📆 <b>За 7 дней</b>\n{lines}\n"
ADMIN_STATS_SECTION_30D = "📆 <b>За 30 дней</b>\n{lines}\n"
ADMIN_STATS_SECTION_TRAINERS = "👥 <b>Тренеры</b>\n{lines}\n"
ADMIN_STATS_SECTION_SIGNALS = "⚠️ <b>Обратить внимание</b>\n{lines}"
ADMIN_STATS_ROW = "• {label}: {value}"
ADMIN_STATS_NOW_BOOKINGS_TODAY = "занятий сегодня"
ADMIN_STATS_NOW_BOOKINGS_WEEK = "занятий на эту неделю (предстоит)"
ADMIN_STATS_NOW_REQUESTS_OPEN = "заявок без отклика (в работе)"
ADMIN_STATS_NOW_PENDING_MOD = "тренеров на модерации"
ADMIN_STATS_7D_BOOKINGS = "записей создано"
ADMIN_STATS_7D_REQUESTS = "заявок от клиентов"
ADMIN_STATS_7D_RESPONSES = "откликов тренеров на заявки"
ADMIN_STATS_7D_TRAINERS = "новых тренеров (регистраций)"
ADMIN_STATS_30D_BOOKINGS = "записей создано"
ADMIN_STATS_30D_REQUESTS = "заявок от клиентов"
ADMIN_STATS_30D_REQUESTS_NEW = "из них ещё без отклика"
ADMIN_STATS_30D_RESPONSES = "откликов тренеров"
ADMIN_STATS_30D_CONVERSION = "заявок получили отклик (конверсия)"
ADMIN_STATS_30D_TRAINERS = "новых тренеров"
ADMIN_STATS_TRAINERS_TOTAL = "всего в системе"
ADMIN_STATS_TRAINERS_ACTIVE_LINKED = "активных и в боте"
ADMIN_STATS_SECTION_SUBSCRIPTIONS = "💳 <b>Подписки (тарифы тренеров)</b>\n{lines}\n"
ADMIN_STATS_SUB_TIER_CRM = "Тир CRM"
ADMIN_STATS_SUB_TIER_ONLINE = "Тир «Онлайн-запись»"
ADMIN_STATS_SUB_TIER_ANALYTICS = "Тир «Аналитика»"
ADMIN_STATS_SUB_TOTAL_WITH_TIER = "Всего с активным тиром"
ADMIN_STATS_SUB_EXPIRING_7D = "Подписка истекает ≤7 дней (тренеров)"
ADMIN_STATS_SUB_ACTIVE_NO_TIER = "Активных тренеров без tier в БД"
ADMIN_SUBSCRIPTION_TIERS_TITLE = "💳 Тарифы подписки тренеров"
ADMIN_SUBSCRIPTION_TIERS_HINT = "Цены, периоды и описания трёх уровней (CRM / Онлайн / Аналитика)."

# Admin: subscription invoices (ERIP / manual catalog checkout)
ADMIN_SUBSCRIPTION_INVOICE_NOTIFY = (
    "💳 <b>Заявка на счёт по подписке</b>\n\n"
    "Счёт № <code>{invoice_id}</code>\n"
    "Тренер: <b>{trainer_name}</b> (internal <code>{trainer_id}</code>)\n"
    "{plan_line}\n"
    "{referral_discount_line}"
    "Сумма: <b>{amount_byn} " + BYR_SIGN + "</b>\n"
    "Период: {period_start} — {period_end}\n\n"
    "{trainer_contact_block}\n\n"
    "<i>Подтвердите оплату или измените состав кнопками ниже.</i>"
)
ADMIN_SUBSCRIPTION_INVOICES_TITLE = "💳 <b>Ожидающие счета по подписке</b> (каталог, ERIP)\n\n"
ADMIN_SUBSCRIPTION_INVOICES_EMPTY = "Нет неоплаченных заявок."
ADMIN_SUBSCRIPTION_INVOICES_LINE = (
    "{n}. №<code>{iid}</code> · тренер <code>{tid}</code> · {name}\n"
    "   {plan_short} · {amt} " + BYR_SIGN + " · {ps}—{pe} · статус <code>{st}</code>\n"
    "   {link}\n"
)
ADMIN_SUBSCRIPTION_INVOICES_FOOTER = "\n<i>Команда: /subscription_invoices</i>"

# Admin: subscription grant flow (per-invoice activate / edit / cancel)
ADMIN_SUBSCRIPTION_GRANT_EDIT_TITLE = (
    "⚙️ <b>Состав подписки № <code>{invoice_id}</code></b>\n"
    "Тренер: <b>{trainer_name}</b> (internal <code>{trainer_id}</code>)\n\n"
    "{plan_line}\n"
    "Сумма: <b>{amount_byn} " + BYR_SIGN + "</b> · период <b>{months}</b>\n\n"
    "«Продлить» = новый период. «Добавить» = модули в текущую подписку, цена пропорциональна остатку.\n"
    "{trainer_contact_block}"
)
ADMIN_SUBSCRIPTION_GRANT_NOT_FOUND = "Счёт не найден или уже неактивен."
ADMIN_SUBSCRIPTION_GRANT_ALREADY_PAID = "Счёт уже подтверждён."
ADMIN_SUBSCRIPTION_GRANT_ACTIVATED = (
    "✅ <b>Подписка активирована</b>\n\n"
    "Счёт № <code>{invoice_id}</code> · тренер <b>{trainer_name}</b>\n"
    "Тариф: <b>{label}</b> · период <b>{months}</b>\n"
    "Сумма: <b>{amount_byn} " + BYR_SIGN + "</b>\n"
    "Действует до <b>{expires_date}</b>.\n\n"
    "Тренеру отправлено уведомление."
)
ADMIN_SUBSCRIPTION_GRANT_FAILED = "Не удалось активировать счёт. Проверьте логи."
ADMIN_SUBSCRIPTION_GRANT_CANCELLED = (
    "❌ Заявка № <code>{invoice_id}</code> отклонена. Тренеру отправлено уведомление."
)
ADMIN_SUBSCRIPTION_GRANT_HELP = (
    "<b>/grant_subscription</b> — выдать подписку конкретному тренеру.\n\n"
    "Использование:\n"
    "<code>/grant_subscription &lt;trainer_id&gt;</code>\n\n"
    "Бот создаст черновик счёта (CRM, 1 мес.) и откроет конструктор — там можно "
    "переключить модули и срок, затем нажать «Активировать»."
)
ADMIN_SUBSCRIPTION_GRANT_NO_TRAINER = "Тренер с id <code>{tid}</code> не найден."
ADMIN_SUBSCRIPTION_GRANT_DRAFT_FAILED = "Не удалось создать черновик счёта. Проверьте, что тариф CRM сконфигурирован."

# Trainer-side notifications when admin acts on a subscription invoice
TRAINER_SUBSCRIPTION_GRANTED_BY_ADMIN = (
    "✅ <b>Подписка активирована</b>\n\n"
    "Тариф: <b>«{label}»</b>\n"
    "Действует до <b>{expires_date}</b>.\n\n"
    "Все включённые модули уже доступны в меню."
)
TRAINER_SUBSCRIPTION_INVOICE_DECLINED = (
    "ℹ️ <b>Заявка на подписку отклонена</b>\n\n"
    "Если это ошибка — напишите в поддержку или оставьте новую заявку в разделе «Подписка»."
)
ADMIN_WELCOME_TRIAL_DAYS_CURRENT = (
    "🧪 <b>Пробный период при первой привязке Telegram</b>\n\n"
    "Сейчас в базе: <b>{days}</b> дн. (полный доступ ко всем модулям: CRM, онлайн-запись, аналитика, группы).\n"
    "Переопределение через <code>TRIAL_PERIOD_DAYS</code> в окружении имеет приоритет."
)
ADMIN_WELCOME_TRIAL_DAYS_SET = "Сохранено: пробный период <b>{days}</b> дн. для новых подписок."
ADMIN_WELCOME_TRIAL_DAYS_INVALID = "Укажите целое число дней от 1 до 365, например: <code>/welcome_trial_days 21</code>"

ADMIN_TRAINER_WELCOME_LINK_HELP = (
    "<b>Welcome-ссылка в тренерский бот</b>\n\n"
    "• <b>Новый тренер</b> — отправьте команду одну: <code>/trainer_welcome_link</code> "
    "(создаётся черновик профиля и одноразовая ссылка; срок токена по умолчанию 14 дн.).\n"
    "• <b>Новый тренер, свой срок токена</b> — "
    "<code>/trainer_welcome_link new 30</code> (1–365 дней).\n"
    "• <b>Уже есть профиль</b> — повторная ссылка: "
    "<code>/trainer_welcome_link 42</code> или <code>/trainer_welcome_link 42 60</code> "
    "(id из базы / карточки модерации).\n\n"
    "<b>Зачем id:</b> только если тренер уже заведён в системе, а ссылка сгорела или истекла — "
    "новому человеку id не нужен."
)
ADMIN_TRAINER_WELCOME_LINK_NO_TRAINER = "Тренер с таким id не найден."
ADMIN_TRAINER_WELCOME_LINK_BAD_ARGS = (
    "Нужен числовой id тренера или формат <code>/trainer_welcome_link new 30</code>. "
    "Справка: <code>/trainer_welcome_link help</code>"
)
ADMIN_TRAINER_WELCOME_LINK_NEW_INTRO = (
    "✨ <b>Новый тренер в системе</b>\n"
    "Профиль (черновик): <code>#{trainer_id}</code> — id для вас в админке и поиске; "
    "тренеру достаточно открыть ссылку ниже.\n\n"
)
ADMIN_TRAINER_WELCOME_LINK_ISSUED = (
    "🔗 <b>Welcome-ссылка для тренера #{trainer_id}</b>\n\n"
    "Действует до: <b>{expires}</b> (одноразовая)\n\n"
    "{link_block}"
)
ADMIN_TRAINER_WELCOME_LINK_BLOCK_NO_USERNAME = (
    "⚠️ В окружении не задан <code>TRAINER_BOT_USERNAME</code> — полная ссылка t.me не собирается.\n\n"
    "Передайте тренеру параметр для бота:\n<code>?start={start_payload}</code>\n\n"
    "После настройки имени бота пересоздайте ссылку командой выше."
)

ADMIN_STATS_SECTION_PASSES_CERTS = "📦 <b>Абонементы и сертификаты</b>\n{lines}\n"
ADMIN_STATS_PASSES_ACTIVE = "абонементов активно (с остатком занятий)"
ADMIN_STATS_PASSES_ISSUED_30D = "абонементов выдано за 30 дней"
ADMIN_STATS_CERTS_ISSUED = "сертификатов выдано всего"
ADMIN_STATS_CERTS_WITH_BALANCE = "сертификатов с остатком (не погашены)"
ADMIN_STATS_CERTS_BALANCE_BYN = "остаток по сертификатам (" + BYR_SIGN + ")"
ADMIN_STATS_CERTS_REDEEMED_30D = "сертификатов погашено за 30 дней"
ADMIN_STATS_SIGNAL_PENDING = "На модерации {n} тренер(ов) — /pending"
ADMIN_STATS_SIGNAL_REQUESTS_OPEN = "Заявок без отклика: {n} — клиенты ждут"
ADMIN_STATS_SIGNAL_REQUESTS_STALE = "Заявок без отклика дольше 7 дней: {n}"
ADMIN_STATS_SIGNAL_NO_BOOKINGS = "За 7 дней ни одной записи при {active} активных тренерах"
ADMIN_STATS_SIGNAL_LOW_CONVERSION = "Низкая конверсия заявка→отклик ({pct}%) за 30 дней"

# Admin: support
ADMIN_SUPPORT_LIST_TITLE = "💬 <b>Обращения в поддержку</b>\n\n"
ADMIN_SUPPORT_ITEM = "#{id} [{role}] {date}\n{text}\n"
ADMIN_SUPPORT_EMPTY = "Нет обращений."
ADMIN_SUPPORT_REPLY_PROMPT = "Напишите текст ответа пользователю (или /cancel для отмены):"
ADMIN_SUPPORT_REPLY_SENT = "Ответ сохранён и отправлен пользователю."
ADMIN_SUPPORT_REPLY_CANCELLED = "Отменено."

# Shared (rate limit)
RATE_LIMIT_MESSAGE = "Слишком много запросов. Подождите минуту и попробуйте снова."
