"""
All user-facing bot messages. Clear names; no hardcoding in handlers.
Prefixes: client bot vs trainer bot.

Voice (UX):
- Client bot: «Вы», нейтрально-дружелюбно; без канцелярита; CTA ведут в меню («Тренеры и запись», «Мои записи»), не в несуществующие команды.
- Trainer bot: «ты», коротко и по делу; пуши: заголовок + суть + что сделать в меню слева.
- Кнопки «назад»/пагинация: префикс ◀️ / ▶️ где уместно; не дублировать десяток эмодзи в одном абзаце.
- Не хардкодить тексты в handlers — только через константы здесь.
"""

# --- Client bot ---
CLIENT_START_WELCOME = (
    "👋 Привет! Здесь можно найти тренера и записаться на занятие. "
    "Нажмите кнопку <b>Главная</b> слева от поля ввода — там каталог, записи и заявки. Помощь: /guide"
)
CLIENT_FALLBACK = "Нажмите кнопку <b>Главная</b> слева от поля ввода. Помощь: /guide"
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
CLIENT_PROFILE_ENTER_NAME = "Напишите, пожалуйста, <b>Имя и Фамилию</b> в одном сообщении (как показывать вас тренерам)."
CLIENT_PROFILE_USE_TELEGRAM_NAME = "Использовать имя из Telegram: {name}?"
CLIENT_BUTTON_USE_TG_NAME = "Да"
CLIENT_BUTTON_ENTER_MANUAL = "Ввести вручную"
CLIENT_PROFILE_NAME_INVALID = "Нужно указать и <b>Имя</b>, и <b>Фамилию</b> в одном сообщении. Например: Иван Петров."
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
    "• <b>Мои записи</b> — ближайшие занятия; отмена — в разделе «Мои записи» или напишите тренеру.\n\n"
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
TRAINER_BUTTON_RESPOND = "✅ Готов взять"
TRAINER_BUTTON_RESPOND_INDEX = "{index}. Готов взять"
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
    "<b>Заявки ждут записи</b>\n\n"
    "Открыто: <b>{count}</b> {requests_word}. Клиент выбрал тебя — нужно записать на слот или написать.\n\n"
    "Детали: меню бота → <b>«Заявки клиентов»</b>."
)
CLIENT_TRAINER_BOOKED_YOU = (
    "<b>Вас записали на занятие</b>\n\n"
    "Тренер: <b>{name}</b>\n"
    "Когда: <b>{date}</b> ({day}) в {time}\n\n"
    "Адрес, детали и отмена — в <b>«Мои записи»</b> (меню бота)."
)
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
TRAINER_DAILY_REQUESTS_REMINDER = (
    "<b>Напоминание: заявки клиентов</b>\n\n"
    "Сейчас открыто: <b>{count}</b> {requests_word} по твоему городу и услугам.\n\n"
    "Открой <b>«Заявки клиентов»</b> в меню — откликнись, чтобы клиент мог записаться или написать тебе."
)
TRAINER_REQUEST_NOTIFICATION = (
    "📩 <b>Новая заявка</b>\n\n"
    "<b>{city}</b> · {service}\n"
    "💬 Комментарий: {comment}\n\n"
    "Дальше: меню → <b>«Заявки клиентов»</b> — отклик и действия под заявкой."
)
TRAINER_REQUEST_NOTIFICATION_NO_COMMENT = (
    "📩 <b>Новая заявка</b>\n\n"
    "<b>{city}</b> · {service}\n\n"
    "Дальше: меню → <b>«Заявки клиентов»</b> — отклик и действия под заявкой."
)
CLIENT_RESPONSE_NOTIFICATION = (
    "<b>Отклик по вашей заявке</b>\n\n"
    "Тренер ответил — откройте список откликов кнопкой ниже: там можно написать или записаться."
)
CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT = (
    "<b>Отклик по вашей заявке</b>\n\n"
    "<b>{responder_name}</b>\n"
    "{comment}\n\n"
    "Ниже — все отклики: можно написать тренеру или выбрать запись."
)
CLIENT_RESPONSE_BUTTON_VIEW = "👤 Посмотреть отклики"
CLIENT_NO_RESPONSE_REMINDER = (
    "<b>Пока без откликов</b>\n\n"
    "Мы ещё раз напомнили тренерам о вашей заявке.\n\n"
    "Проще не ждать: откройте каталог в «Настройках» и запишитесь к подходящему тренеру. "
    "Как только кто-то откликнется — пришлём отдельное сообщение."
)
CLIENT_BOOKING_CANCELLED_BY_TRAINER = (
    "<b>Запись отменена тренером</b>\n\n"
    "Было: <b>{date}</b> ({day}) в {time}\n\n"
    "Выберите другое время или тренера: <b>Тренеры и запись</b> в меню бота."
)
CLIENT_BOOKING_CONFIRMED_BY_TRAINER = (
    "<b>Запись подтверждена</b>\n\n"
    "Когда: <b>{date}</b> ({day}) {time}\n"
    "Тренер: {trainer_name}\n\n"
    "Детали и адрес — в «Мои записи»."
)
CLIENT_BOOKING_DECLINED_BY_TRAINER = (
    "<b>Запись не состоится</b>\n\n"
    "Слот: <b>{date}</b> ({day}) {time}\n"
    "Комментарий тренера: {reason}\n\n"
    "Можно выбрать другое время или тренера в каталоге."
)
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
CLIENT_CERT_BOUND = "Сертификат привязан к вашему аккаунту. Можете записаться к тренеру или открыть сертификаты."
# Generic / pass invite links (no cert) — name HTML-escaped in handler
CLIENT_WELCOME_INVITE = (
    "Привет! Вас пригласил тренер <b>{name}</b>.\n\n"
    "{cta}"
)
CLIENT_WELCOME_INVITE_CTA_WEBAPP = (
    "Нажмите «Записаться» — откроется приложение: выберите время и подтвердите запись."
)
CLIENT_WELCOME_INVITE_CTA_INLINE = (
    "Нажмите «Записаться» — покажем свободные слоты или шаги записи."
)
# Backwards compat (tests / old imports); prefer CLIENT_WELCOME_INVITE
CLIENT_WELCOME_REF = (
    "Привет! Вас пригласил тренер. Нажмите «Записаться», чтобы продолжить."
)
CLIENT_PASS_WELCOME = (
    "<b>{name}</b> пригласил вас. Запишитесь на занятие или купите абонемент — кнопки ниже."
)
CLIENT_BUTTON_BUY_PASS = "Купить абонемент"
CLIENT_WELCOME_LINK_USED = "Эта ссылка уже использована или недействительна. Попросите тренера прислать новую ссылку."
CLIENT_CERT_CODE_INVALID = "Код сертификата не найден или уже использован другим пользователем. Проверьте ссылку или обратитесь к тренеру."
CLIENT_MY_CERTIFICATES_INTRO = "🎁 Ваши сертификаты: номинал, код, статус. Нажмите кнопку ниже."
# Reminders: fixed date/time (no "через" — notifications may be delayed by poll interval).
CLIENT_REMINDER_24H = (
    "<b>Напоминание о занятии</b>\n\n"
    "📅 <b>{date}</b> ({day}) в {time}\n"
    "⏱ Длительность: {duration} мин.\n\n"
    "Адрес и детали — в <b>«Мои записи»</b> (меню бота)."
)
CLIENT_REMINDER_2H = (
    "<b>Скоро занятие</b>\n\n"
    "📅 <b>{date}</b> ({day}) в {time}\n"
    "⏱ Длительность: {duration} мин.\n\n"
    "Адрес и детали — в <b>«Мои записи»</b> (меню бота)."
)
CLIENT_BOOKING_COMPLETED = (
    "<b>Занятие завершено</b>\n\n"
    "Было: <b>{date}</b> ({day}) в {time}\n\n"
    "Оцените тренера и при желании оставьте отзыв — кнопки ниже."
)
# Inactive: 10 / 30 days since last session — friendly nudge to book again (once per client per kind)
CLIENT_INACTIVE_10_DAYS = (
    "<b>Давно не виделись</b>{name}\n\n"
    "С прошлого занятия прошла больше недели. Загляните в каталог — выберите тренера и удобное время.\n\n"
    "Кнопка ниже ведёт к записи."
)
CLIENT_INACTIVE_30_DAYS = (
    "<b>Месяц без занятий</b>{name}\n\n"
    "Если хотите вернуться в форму — откройте каталог и запишитесь, когда будет удобно.\n\n"
    "Кнопка ниже ведёт к записи."
)
CLIENT_BUTTON_LEAVE_FEEDBACK = "⭐ Оставить отзыв и оценку"
CLIENT_BUTTON_REPEAT_SAME_TIME = "🔄 Повторить в это же время"
CLIENT_BUTTON_BECOME_REGULAR = "📅 Стать постоянным клиентом"
CLIENT_REPEAT_BOOKED = "✅ Записали вас на следующую неделю на <b>{date}</b> ({day}) {time}."
CLIENT_REPEAT_SLOT_BOOKED = (
    "На это время на следующую неделю слот уже занят. "
    "Можете <b>стать постоянным</b> — тогда на следующие недели это время будет резервироваться за вами при создании расписания; "
    "или выбрать другое время в каталоге."
)
CLIENT_REPEAT_SLOT_TAKEN_BY_REGULAR = (
    "На это время уже закреплён другой постоянный клиент. "
    "Выберите другое время в каталоге — там видны все свободные слоты."
)
CLIENT_REPEAT_NO_SLOT_YET = (
    "На это время на следующую неделю в расписании тренера пока нет окна. "
    "Когда тренер добавит слот — мы запишем вас и напишем."
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
    "<b>Свободное окно</b>\n\n"
    "<b>{date}</b> ({day}) в {time}\n"
    "Тренер: <b>{trainer_name}</b>\n\n"
    "Записаться — кнопка ниже."
)
CLIENT_BUTTON_BOOK_THIS_SLOT = "Записаться"
CLIENT_FEEDBACK_RATE_PROMPT = "Поставьте оценку тренеру от 1 до 5 звёзд:"
CLIENT_FEEDBACK_REVIEW_PROMPT = "Напишите отзыв (необязательно) или нажмите «Пропустить»:"
CLIENT_FEEDBACK_SKIP = "Пропустить"
CLIENT_FEEDBACK_THANKS = "Спасибо за отзыв!"
TRAINER_BOOKING_COMPLETED = (
    "<b>Занятие завершено</b>\n\n"
    "Было: <b>{date}</b> ({day}) в {time}\n\n"
    "О клиенте — отзыв по желанию (кнопка ниже)."
)
TRAINER_NO_PASS_FOR_SERVICE = (
    "<b>Без списания абонемента</b>\n\n"
    "У клиента нет подходящего абонемента по этой услуге — занятие закрыто без списания.\n\n"
    "Клиент: {client_name}\n"
    "Слот: {date} {time}\n"
    "Услуга: {service_name}"
)
TRAINER_BUTTON_LEAVE_FEEDBACK = "✍️ Оставить отзыв"
TRAINER_BUTTON_CLIENT_CARD_WEBAPP = "👤 Карточка и заметка"
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
    "🎯 <b>Добро пожаловать в тренерскую платформу</b>\n\n"
    "Здесь — <b>расписание</b>, <b>клиентская база</b>, <b>онлайн-запись</b> из каталога, "
    "<b>абонементы</b>, <b>сертификаты</b> и <b>аналитика</b> в одном месте.\n\n"
    "Пошаговый чеклист (профиль → слоты → первая запись) и <b>FAQ</b> — на <b>главной</b> мини-приложения "
    "(команда <b>/home</b> или раздел «Обзор»), блок <b>«Первые шаги»</b>.\n\n"
    "После активации аккаунта тебе будет доступен <b>пробный период на максимальном тарифе</b> — "
    "можно спокойно оценить продукт. Ниже — что сделать прямо сейчас; начни с <b>«Обзор»</b>."
)
TRAINER_AFTER_LINK_STEP_BLOCKED = (
    "<b>Сейчас</b>: заполни анкету в мини-приложении — это несколько минут. "
    "Без этого не откроются расписание и заявки — так мы защищаем и тебя, и клиентов в каталоге.\n\n"
    "👉 Нажми <b>«Обзор»</b> ниже — там чеклист «Первые шаги» и понятный порядок действий; "
    "анкету заполняй в разделе <b>«Профиль»</b> внутри мини-приложения (меню слева или переход из чеклиста)."
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
# После первой привязки по ссылке (active + пробный тариф «Аналитика»)
TRAINER_WELCOME_TRIAL_ACTIVATED = (
    "🎁 <b>Пробный период на максимальном тарифе</b>\n\n"
    "Для тебя активирован тариф <b>«{tier_name}»</b> в пробном режиме "
    "до <b>{expires_date}</b>.\n\n"
    "Сейчас доступны <b>все инструменты</b> платформы: расписание, CRM, онлайн-запись, "
    "абонементы, сертификаты и аналитика.\n\n"
    "Когда пробный период закончится, выбери платный тариф в разделе "
    "<b>«Подписка»</b> в меню бота — мы напомним заранее."
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
    "/pending — показать тренеров на модерацию."
)
ADMIN_NO_ACCESS = "У вас нет доступа к этому боту."
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
    "✅ Раздел «Образование» в твоём профиле прошёл модерацию."
)
TRAINER_EDUCATION_MODERATION_REJECTED = (
    "⚠️ Раздел «Образование» отправлен на доработку.\n\nКомментарий модератора:\n{reason}"
)
# Push to trainer bot when admin saves «Нужны правки» comment (moderation_feedback).
TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH = (
    "✏️ <b>Комментарий модератора к анкете</b>\n\n{feedback}"
)
TRAINER_PROFILE_MODERATION_FEEDBACK_PUSH_FOOTER = "\n\nВнеси правки в мини-приложении «Профиль» (кнопка ниже)."
TRAINER_MODERATION_PROFILE_APPROVED = (
    "✅ <b>Анкета одобрена</b>\n\n"
    "Ты в каталоге — клиенты могут тебя найти и записаться."
)
TRAINER_MODERATION_PROFILE_REJECTED = (
    "❌ <b>Анкета не прошла модерацию</b>\n\n"
    "Тебя нет в каталоге. Если это ошибка — напиши в поддержку: /guide"
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
TRAINER_CREATE_BOOKING_DONE = (
    "✅ Записали клиента <b>{client_name}</b> на <b>{date}</b> ({day}) {time}."
)
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
TRAINER_BOOKING_CANCELLED_BY_CLIENT = (
    "<b>Клиент отменил запись</b>\n\n"
    "Кто: <b>{client_name}</b>\n"
    "Когда было: <b>{date}</b> ({day}) в {time}\n"
    "Причина: {reason}"
)
TRAINER_BOOKING_CANCELLED_BY_CLIENT_NO_REASON = (
    "<b>Клиент отменил запись</b>\n\n"
    "Кто: <b>{client_name}</b>\n"
    "Когда было: <b>{date}</b> ({day}) в {time}"
)
TRAINER_BOOKINGS_BUTTON_DECLINE = "❌ Отклонить"
TRAINER_BOOKINGS_BUTTON_MAKE_REGULAR = "📅 Сделать постоянным клиентом"
TRAINER_BOOKINGS_BUTTON_REMOVE_REGULARITY = "📅 Снять регулярность"
TRAINER_RECURRING_DONE = "Клиент закреплён как постоянный: каждую неделю в это время слот будет автоматически бронироваться за ним."
TRAINER_RECURRING_REMOVED = "Регулярность снята."
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
TRAINER_BOOKING_NOTIFICATION = (
    "<b>Новая запись</b>\n\n"
    "📅 <b>{date}</b> ({day}) · {time}\n\n"
    "👤 {client_name}\n"
    "📱 {phone}\n"
    "🎯 {service}\n"
    "📍 {city}\n"
    "🏟 {arenas}\n"
    "💬 {comment}\n\n"
    "Нажми <b>Подтвердить</b> или <b>Отклонить</b>. Написать — отдельная кнопка.\n\n"
    "<i>Слот уже занят; клиент получит напоминания автоматически.</i>"
)
TRAINER_BOOKING_NOTIFICATION_NO_COMMENT = (
    "<b>Новая запись</b>\n\n"
    "📅 <b>{date}</b> ({day}) · {time}\n\n"
    "👤 {client_name}\n"
    "📱 {phone}\n"
    "🎯 {service}\n"
    "📍 {city}\n"
    "🏟 {arenas}\n\n"
    "Нажми <b>Подтвердить</b> или <b>Отклонить</b>. Написать — отдельная кнопка.\n\n"
    "<i>Слот уже занят; клиент получит напоминания автоматически.</i>"
)
TRAINER_BOOKING_CONFIRMED = (
    "Запись подтверждена.\n\n"
    "Клиент: {client_display}\n"
    "Дата и время: {date} ({day}) {time}"
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
    "<b>Нужно подтвердить запись</b>\n\n"
    "Занятие с <b>{client_display}</b> начинается в ближайшие два часа.\n"
    "Время: <b>{date}</b> ({day}) в {time}\n\n"
    "Подтверди или отклони — чтобы клиент видел актуальный статус."
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
    "(на сумму {certificate_balance_byn} BYN), погашено за 30 дн.: {certificates_redeemed_30d}"
)
TRAINER_STATS_OPEN_APP = "📊 Открой статистику в приложении — графики, тренды и инсайты по работе."
TRAINER_BUTTON_STATS_APP = "📊 Открыть статистику"
TRAINER_SUBSCRIPTION_REMINDER = (
    "<b>Подписка скоро закончится</b>\n\n"
    "Действует до <b>{expires_date}</b>.\n\n"
    "Оплати до этой даты (можно заранее). Иначе доступ к каталогу и записям временно отключится."
)
TRAINER_SUBSCRIPTION_REMINDER_TRIAL = (
    "<b>Пробный период скоро закончится</b>\n\n"
    "Полный доступ действует до <b>{expires_date}</b>.\n\n"
    "Чтобы не прерывать работу с клиентами, выбери платный тариф в разделе "
    "<b>«Подписка»</b> — удобнее всего сразу после окончания пробного периода."
)
TRAINER_BUTTON_PAY_SUBSCRIPTION = "Оплатить подписку"
# /subscription — мини-апп trainer-subscription
TRAINER_BUTTON_SUBSCRIPTION_CONSTRUCTOR = "Подписки"
TRAINER_SUBSCRIPTION_WITH_TIER = (
    "📋 Тариф: <b>{tier_name}</b>\n"
    "До <b>{expires_date}</b>"
)
TRAINER_SUBSCRIPTION_WITHOUT_TIER = "📋 Подписка не активна."
TRAINER_SUBSCRIPTION_ACTIVE = (
    "Подписка на платформу активна до <b>{expires_date}</b>. Ты в каталоге.\n\n"
    "Кнопка ниже — оплата за <b>следующий период</b> (после этой даты). Можно выбрать срок: месяц, 3 мес, год или 1,5 года."
)
TRAINER_SUBSCRIPTION_EXPIRED = (
    "Подписка истекла. Оплати новый период (месяц / 3 мес / год / 1,5 года), чтобы снова быть в каталоге."
)

# Subscription tier access messages
TRAINER_TIER_REQUIRED_CRM = (
    "⚠️ Для этой функции нужна подписка уровня <b>CRM</b> или выше.\n\n"
    "Оформи подписку, чтобы использовать расписание, клиентскую базу, абонементы, сертификаты "
    "и профиль в каталоге."
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
ADMIN_WELCOME_TRIAL_DAYS_CURRENT = (
    "🧪 <b>Пробный период при первой привязке Telegram</b>\n\n"
    "Сейчас в базе: <b>{days}</b> дн. (макс. тариф «Аналитика»).\n"
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
ADMIN_STATS_CERTS_BALANCE_BYN = "остаток по сертификатам (BYN)"
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
