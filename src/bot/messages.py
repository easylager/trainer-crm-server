"""
All user-facing bot messages. Clear names; no hardcoding in handlers.
Prefixes: client bot vs trainer bot.
"""

# --- Client bot ---
CLIENT_START_WELCOME = "Привет! Здесь можно найти тренера и записаться на занятие. Все разделы — в меню слева от поля ввода. Подробнее: /guide"
CLIENT_FALLBACK = "Используйте меню слева от поля ввода — там все разделы бота. Инструкция: /guide"
CLIENT_CATALOG_LOADING = "Загружаю Выбор тренера..."
CLIENT_CATALOG_HEADER = "Вот наши тренеры:"
CLIENT_CATALOG_EMPTY = "Пока нет активных тренеров. Загляни позже."
CLIENT_CATALOG_PAGINATION_LEAVE_REQUEST = "Не нашли подходящего тренера? Оставьте заявку — мы подберём для вас тренера."
CLIENT_CHOOSE_CITY = "Выбери город:"
CLIENT_CHOOSE_SERVICE = "Выбери услугу:"
CLIENT_TRAINER_CARD = (
    "<b>{name}</b>\n"
    "Рейтинг: {rating}\n"
    "Возраст: {age} лет\n"
    "Опыт: {experience}\n"
    "Арены: {arenas}\n"
    "Услуги и цены: {services_prices}\n"
    "{description}"
)
CLIENT_TRAINER_CARD_NO_RATING = "—"
CLIENT_TRAINER_CARD_NO_EXPERIENCE = "Опыт: не указан"
CLIENT_BUTTON_SELECT_TRAINER = "Выбрать"
CLIENT_TRAINER_SELECTED = "Выбран: <b>{name}</b>. Что дальше?"
CLIENT_BUTTON_BOOK = "Записаться"
CLIENT_BUTTON_BACK_TO_CATALOG = "В каталог"
CLIENT_BUTTON_ANOTHER_TRAINER = "Выбрать другого тренера"
CLIENT_BOOK_CHOOSE_SLOT = "📅 <b>Выберите время</b>\n\nДоступные слоты (эта и следующая неделя):"
CLIENT_BOOK_NO_SLOTS = "У этого тренера пока нет свободных слотов. Загляните позже или выберите другого тренера."
CLIENT_BOOK_NO_TRAINER = "Сначала выберите тренера в каталоге."
CLIENT_BOOK_ENTER_PHONE = "Введите номер телефона (например +375291234567) или нажмите кнопку ниже, чтобы отправить контакт."
CLIENT_BOOK_ENTER_COMMENT = "Комментарий к записи (необязательно). Напишите текст или нажмите «Пропустить»."
CLIENT_BOOK_SKIP_COMMENT = "Пропустить"
CLIENT_BOOK_SUCCESS = "✅ Вы записаны на <b>{date}</b> ({day}) {time}."
CLIENT_BOOK_WHAT_NEXT = "Что дальше?"
CLIENT_BOOK_BUTTON_BACK = "◀️ Назад"
CLIENT_BOOK_PHONE_INVALID = "Нужен номер телефона. Отправьте текст (например +375291234567) или нажмите «Отправить контакт»."
CLIENT_BOOK_BUTTON_SEND_CONTACT = "📱 Отправить контакт"
CLIENT_BOOK_RECORDED = "Запись оформлена."
CLIENT_BOOK_COMMENT_OR_BUTTON = "Напишите комментарий или нажмите кнопку:"

# Client: errors and hints (what to do next)
CLIENT_ERROR_BOOKING_CLOSED = "Эта запись уже закрыта или недоступна. Выберите другого тренера или время в каталоге."
CLIENT_ERROR_BOOKING_UNAVAILABLE = "Эта запись недоступна. Выберите слот в каталоге или нажмите «Записаться»."
CLIENT_ERROR_NO_CITIES = "Нет доступных городов. Выберите город позже или напишите в поддержку."
CLIENT_ERROR_NO_SERVICES = "Нет доступных услуг. Выберите услугу позже или напишите в поддержку."
CLIENT_ERROR_NO_CITIES_ADMIN = "Нет доступных городов. Обратитесь к администратору."
CLIENT_ERROR_NO_SERVICES_ADMIN = "Нет доступных услуг. Обратитесь к администратору."
CLIENT_ERROR_CHOOSE_CITY_FIRST = "Сначала выберите город в настройках (меню → Настройки)."
CLIENT_ERROR_REQUEST_NOT_FOUND = "Заявка не найдена. Откройте «Мои заявки» и попробуйте снова."
CLIENT_ERROR_TRY_AGAIN = "Произошла ошибка. Попробуйте ещё раз или введите /guide."
CLIENT_ERROR_TRAINER_NOT_FOUND = "Тренер не найден. Откройте каталог и выберите тренера заново."

# Client: /guide — instruction only; describes main menu (left of input), no buttons under message
CLIENT_GUIDE = (
    "📖 <b>Инструкция</b>\n\n"
    "Все разделы — в <b>меню слева от поля ввода</b>. Что делает каждый пункт:\n\n"
    "📍 <b>Выбор тренера</b>\n"
    "Настройте город, услугу и при желании арену — откроется каталог. Выберите тренера, чтобы записаться к нему или посмотреть профиль.\n\n"
    "📅 <b>Записаться к выбранному тренеру</b>\n"
    "Выберите время из свободных слотов, укажите телефон и при желании комментарий. После записи придёт подтверждение и напоминания перед занятием.\n\n"
    "📋 <b>Оставить заявку</b>\n"
    "Нет подходящего тренера в каталоге? Оставьте заявку — тренеры по вашему городу и услуге откликнутся, вы сможете записаться или написать.\n\n"
    "📩 <b>Мои заявки и отклики</b>\n"
    "Ваши заявки и список откликнувшихся тренеров: записаться к одному из них или написать в Telegram.\n\n"
    "📆 <b>Мои записи</b>\n"
    "Ближайшие занятия: дата, время, тренер. Для отмены — напишите тренеру (ссылка в списке)."
)

# --- Settings (my choices) ---
CLIENT_SETTINGS_TITLE = "⚙️ <b>Настройки</b>\n\nВаши текущие выборы. Нажми кнопку, чтобы изменить."
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
CLIENT_SETTINGS_NEED_CITY_SERVICE = "Сначала выберите город и услугу в настройках — тогда станет доступен выбор тренера."

# --- Leave request (no suitable trainer found) ---
CLIENT_REQUEST_BUTTON_LEAVE = "Оставить заявку на подбор тренера"
CLIENT_BUTTON_LEAVE_REQUEST = "📋 Оставить заявку"
CLIENT_REQUEST_BUTTON_EMPTY_CATALOG = "Оставить заявку — мы подберём вариант"
CLIENT_REQUEST_PROMPT_COMMENT = "Опишите кратко, что ищете (необязательно). Или нажмите «Пропустить»."
CLIENT_REQUEST_SKIP = "Пропустить"
CLIENT_REQUEST_NEED_CITY_SERVICE = "Сначала выберите город и услугу в настройках — тогда можно оставить заявку."
CLIENT_REQUEST_SUCCESS = "Заявка принята. Когда появится подходящий тренер — напишем вам."
CLIENT_REQUEST_BACK = "◀️ В настройки"
CLIENT_BUTTON_BACK_TO_MENU = "◀️ В главное меню"

# --- My requests & responses (client sees who responded) ---
CLIENT_MY_REQUESTS_TITLE = "📋 <b>Мои заявки</b>\n\nПод каждой заявкой — кнопка «Показать отклики» или «Пока нет откликов»."
CLIENT_MY_REQUESTS_EMPTY = "У вас пока нет заявок. Оставьте заявку в настройках или когда каталог пуст."
CLIENT_MY_REQUESTS_ROW = "{index}. 📍 {city}, {service}. Комментарий: {comment}"
CLIENT_MY_REQUESTS_ROW_NO_COMMENT = "{index}. 📍 {city}, {service}"
CLIENT_MY_REQUESTS_RESPONSES_HEADER = "Откликнулись ({count}):"
CLIENT_MY_REQUESTS_BUTTON_RESPONSES = "{index}. Показать отклики ({count})"
CLIENT_MY_REQUESTS_NO_RESPONSES = "{index}. Пока нет откликов"
CLIENT_BUTTON_MY_REQUESTS = "Мои заявки и отклики"
CLIENT_BUTTON_MY_BOOKINGS = "Мои записи"
CLIENT_MY_BOOKINGS_TITLE = "📋 <b>Мои записи</b>"
CLIENT_MY_BOOKINGS_CANCEL_HINT = "Для отмены записи напишите вашему тренеру в Telegram. Имя тренера в списке ниже — ссылка для перехода в чат."
CLIENT_MY_BOOKINGS_EMPTY = "У вас пока нет записей. Выберите тренера в каталоге и нажмите «Записаться»."
CLIENT_MY_BOOKINGS_ROW = "{index}. {date} ({day}) {time} — {trainer_display}"
CLIENT_BUTTON_BACK_FROM_BOOKINGS = "◀️ В меню"
CLIENT_BUTTON_RESPONDER_WRITE = "✉️ Написать"
CLIENT_BUTTON_RESPONDER_BOOK = "Записаться"
CLIENT_BUTTON_RESPONDER_PROFILE = "👤 Профиль"
CLIENT_BUTTON_BACK_TO_RESPONSES = "◀️ Назад к откликам"
CLIENT_BUTTON_BACK_TO_REQUESTS = "◀️ Назад к заявкам"
CLIENT_RESPONDER_NO_TG = "(тренер ещё не в боте — только запись)"
CLIENT_PICK_TRAINER_DONE = "Тренер выбран. Нажмите «Записаться» в меню или ниже, чтобы выбрать время."

# --- Trainer bot: client requests (respond = ready to fulfill) ---
TRAINER_REQUESTS_TITLE = "📋 <b>Заявки клиентов</b>\n\nПо вашему городу и услугам. Под каждой заявкой — кнопка «Готов взять» (откликнуться) или «Вы откликнулись»."
TRAINER_REQUESTS_EMPTY = "Пока нет заявок по вашему профилю (город + услуги). Заполните профиль на сайте."
TRAINER_REQUEST_ROW = "{index}. 📍 {city}, {service}. Комментарий: {comment}"
TRAINER_REQUEST_ROW_NO_COMMENT = "{index}. 📍 {city}, {service}"
TRAINER_BUTTON_REQUESTS = "📋 Заявки клиентов"
TRAINER_BUTTON_RESPOND = "Готов взять"
TRAINER_BUTTON_RESPOND_INDEX = "{index}. Готов взять"
TRAINER_RESPONDED = "Вы откликнулись"
TRAINER_RESPONDED_INDEX = "{index}. Вы откликнулись"
TRAINER_RESPOND_SUCCESS = "Вы откликнулись на заявку. Клиент увидит вас в списке и сможет записаться или написать."

# --- Notifications ---
TRAINER_REQUEST_NOTIFICATION = (
    "📩 <b>Новая заявка клиента</b>\n\n"
    "📍 {city}, {service}\n"
    "Комментарий: {comment}\n\n"
    "Откройте бота → «Заявки клиентов», чтобы откликнуться."
)
TRAINER_REQUEST_NOTIFICATION_NO_COMMENT = (
    "📩 <b>Новая заявка клиента</b>\n\n"
    "📍 {city}, {service}\n\n"
    "Откройте бота → «Заявки клиентов», чтобы откликнуться."
)
CLIENT_RESPONSE_NOTIFICATION = (
    "📩 По вашей заявке откликнулся тренер.\n\n"
    "Откройте «Мои заявки» в настройках — там можно написать тренеру или записаться."
)
CLIENT_BOOKING_CANCELLED_BY_TRAINER = (
    "⚠️ Тренер отменил запись на <b>{date}</b> ({day}) в {time}.\n\n"
    "Можете выбрать другое время или другого тренера: /book или «Настройки» → каталог."
)
# Reminders (24h and 2h before slot). Placeholders: date, day, time.
CLIENT_REMINDER_24H = "⏰ Напоминание: через 24 часа у вас занятие — <b>{date}</b> ({day}) {time}."
CLIENT_REMINDER_2H = "⏰ Напоминание: через 2 часа занятие — <b>{date}</b> ({day}) {time}."
CLIENT_BOOKING_COMPLETED = (
    "✅ Занятие <b>{date}</b> ({day}) {time} завершено.\n\n"
    "Поделитесь впечатлениями — поставьте оценку тренеру и при желании напишите отзыв."
)
CLIENT_BUTTON_LEAVE_FEEDBACK = "⭐ Оставить отзыв и оценку"
CLIENT_FEEDBACK_RATE_PROMPT = "Поставьте оценку тренеру от 1 до 5 звёзд:"
CLIENT_FEEDBACK_REVIEW_PROMPT = "Напишите отзыв (необязательно) или нажмите «Пропустить»:"
CLIENT_FEEDBACK_SKIP = "Пропустить"
CLIENT_FEEDBACK_THANKS = "Спасибо за отзыв!"
TRAINER_BOOKING_COMPLETED = (
    "✅ Занятие <b>{date}</b> ({day}) {time} завершено.\n\n"
    "Поделитесь впечатлениями (необязательно)."
)
TRAINER_BUTTON_LEAVE_FEEDBACK = "✍️ Оставить отзыв"
TRAINER_FEEDBACK_PROMPT = "Напишите отзыв о занятии (необязательно, можно коротко):"
TRAINER_FEEDBACK_THANKS = "Спасибо! Отзыв сохранён."
TRAINER_START_WELCOME = (
    "Привет!\n\n"
    "Ты в боте как <b>тренер</b>. Все разделы — в <b>меню слева от поля ввода</b>: расписание, заявки клиентов, записи.\n\n"
    "Подробная инструкция по каждому пункту: /guide"
)
TRAINER_ONLY_VIA_SITE = "Этот бот только для тренеров. Подключение по ссылке с сайта после регистрации и оплаты."
TRAINER_LINK_SUCCESS = (
    "Аккаунт тренера привязан к этому Telegram.\n\n"
    "Все разделы — в <b>меню слева от поля ввода</b>. Инструкция: /guide"
)
TRAINER_LINK_INVALID = "Ссылка недействительна или уже использована. Получи новую на сайте после оплаты."
TRAINER_FALLBACK = "Используйте меню слева от поля ввода — там все разделы. Инструкция: /guide"

# Trainer: errors and hints
TRAINER_ERROR_BOOKING_NOT_FOUND = "Запись не найдена. Обновите список «Мои записи»."
TRAINER_ERROR_CANCEL_FAILED = "Не удалось отменить запись (уже отменена или не найдена). Обновите «Мои записи»."
TRAINER_ERROR_BOOKING_CLOSED_OR_NOT_FOUND = "Запись не найдена или уже закрыта. Откройте «Мои записи» заново."
TRAINER_ERROR_FEEDBACK_SAVE_FAILED = "Не удалось сохранить отзыв. Попробуйте ещё раз или пропустите."
TRAINER_ERROR_RESPOND_FAILED = "Не удалось откликнуться (заявка уже закрыта или вы уже откликались). Обновите «Заявки клиентов»."

# Trainer: /guide — instruction only; describes main menu (left of input), no buttons under message
TRAINER_GUIDE = (
    "📖 <b>Инструкция (тренер)</b>\n\n"
    "Все разделы — в <b>меню слева от поля ввода</b>. Что делает каждый пункт:\n\n"
    "📅 <b>Редактор расписания</b>\n"
    "Настройка шаблона недели (день и время) и слотов на текущую или следующую неделю. Можно применить шаблон на неделю целиком — свободные слоты станут доступны клиентам для записи.\n\n"
    "📋 <b>Мое расписание</b>\n"
    "Просмотр слотов на эту и следующую неделю: свободен или занят. Удобно сверяться с календарём.\n\n"
    "📩 <b>Заявки клиентов</b>\n"
    "Заявки по вашему городу и услугам. Откликнитесь — клиент увидит вас в списке и сможет записаться или написать. Новые заявки приходят уведомлением.\n\n"
    "✉️ <b>Мои записи</b>\n"
    "Список записей: контакт клиента, дата и время. Можно написать клиенту в Telegram или отменить запись (перед отменой предупредите клиента).\n\n"
    "📊 <b>Статистика</b>\n"
    "Занятия за неделю и месяц, загрузка расписания, новые клиенты за 30 дней и ваш рейтинг."
)

# --- Admin bot: trainer moderation ---
ADMIN_START = (
    "Привет! Это админ-бот для модерации тренеров.\n\n"
    "Команды:\n"
    "/pending — показать тренеров на модерацию."
)
ADMIN_NO_ACCESS = "У вас нет доступа к этому боту."
ADMIN_PENDING_EMPTY = "Нет тренеров в очереди на модерацию."
ADMIN_TRAINER_CARD = (
    "<b>Тренер #{id}</b>\n"
    "Имя: {name}\n"
    "Возраст: {age}\n"
    "Опыт: {experience}\n\n"
    "{description}"
)
ADMIN_BUTTON_APPROVE = "✅ Одобрить"
ADMIN_BUTTON_REJECT = "❌ Отклонить"
ADMIN_BUTTON_NEEDS_EDIT = "✏️ Нужны правки"
ADMIN_APPROVED = "Тренер одобрен и станет виден клиентам."
ADMIN_REJECTED = "Тренер отклонён и не будет виден клиентам."
ADMIN_NEEDS_EDIT_PROMPT = "Напишите текст фидбека для тренера (он увидит его в личном кабинете на сайте):"
ADMIN_NEEDS_EDIT_DONE = "Фидбек сохранён. Тренер остаётся в статусе «на модерации» и увидит текст на сайте."
ADMIN_NEEDS_EDIT_CANCELLED = "Отменено."

# Trainer schedule (by calendar week + template for quick apply)
TRAINER_BUTTON_SCHEDULE = "📅 Редактор расписания"
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
# Short labels for narrow mobile screens (dates appended in code)
TRAINER_BUTTON_APPLY_THIS_WEEK = "▶ Применить шаблон на эту нед."
TRAINER_BUTTON_APPLY_NEXT_WEEK = "▶ Применить шаблон на след. нед."
TRAINER_SCHEDULE_CONFIRM_OVERWRITE = (
    "⚠️ <b>Внимание:</b> это <b>полностью заменит</b> расписание на неделю {start}–{end}.\n\n"
    "Все свободные слоты будут удалены, новые созданы из шаблона. Занятые слоты не трогаем.\n\n"
    "Продолжить?"
)
TRAINER_SCHEDULE_BUTTON_CONFIRM = "Продолжить"
TRAINER_BUTTON_MY_SLOTS = "📋 Мое расписание"
TRAINER_BUTTON_MY_BOOKINGS = "📋 Мои записи"
TRAINER_BUTTON_BACK = "Назад"
TRAINER_BUTTON_BACK_TO_SCHEDULE = "◀️ Редактор расписания"
TRAINER_BUTTON_BACK_TO_MENU = "◀️ В главное меню"
TRAINER_SCHEDULE_CHOOSE_WEEK = "На какую неделю добавляешь слоты?"
TRAINER_SCHEDULE_THIS_WEEK = "Эта неделя ({start}–{end})"
TRAINER_SCHEDULE_NEXT_WEEK = "Следующая неделя ({start}–{end})"
TRAINER_SCHEDULE_CHOOSE_DAY = "Выбери день недели:"
TRAINER_SCHEDULE_CHOOSE_TIME = "Отметь все нужные часы (повторное нажатие снимает отметку), затем «Готово»:"
TRAINER_SCHEDULE_CHOOSE_DURATION = "Длительность занятия (для всех выбранных слотов):"
TRAINER_SCHEDULE_DONE = "Готово ({count})"
TRAINER_SCHEDULE_CANCEL_ADD = "Отмена"
TRAINER_SCHEDULE_SELECT_AT_LEAST_ONE = "Выбери хотя бы один час."
TRAINER_SCHEDULE_ADDED = "Слот добавлен в шаблон."
TRAINER_SCHEDULE_ADDED_MULTI = "В шаблон добавлено слотов: {count}."
TRAINER_SCHEDULE_DAY_CLEARED = "Слоты на этот день в шаблоне убраны."
TRAINER_SCHEDULE_DAY_CLEARED_WEEK = "Слоты на этот день убраны. Добавить слоты на другой день?"
TRAINER_SCHEDULE_TEMPLATE_CHOOSE_ANOTHER_DAY = "Выбери другой день или вернись в расписание."
TRAINER_SCHEDULE_ADDED_TO_WEEK = "На выбранную неделю добавлено слотов: {count}."
TRAINER_SCHEDULE_ADDED_TO_WEEK_MORE = "На неделю добавлено слотов: {count}. Добавить слоты на другой день?"
TRAINER_SCHEDULE_GENERATED = "Расписание на неделю заменено. Создано слотов: {count}. Посмотреть: «Мое расписание»."
TRAINER_SCHEDULE_GENERATED_NONE = "Расписание на неделю заменено. В шаблоне нет слотов на эти дни — неделя очищена от свободных слотов."
TRAINER_SCHEDULE_DELETED = "Слот удалён из шаблона."
TRAINER_DATE_FMT = "%d.%m"  # 18.02

# Applied slots (view only)
TRAINER_SLOTS_TITLE = "📋 <b>Применённое расписание</b>\n\nСлоты, в которые клиенты могут записаться:"
TRAINER_SLOTS_THIS_WEEK_HEADER = "\n<b>Эта неделя ({start}–{end})</b>"
TRAINER_SLOTS_NEXT_WEEK_HEADER = "\n<b>Следующая неделя ({start}–{end})</b>"
TRAINER_SLOTS_EMPTY = "Пока нет слотов. Добавь слоты на неделю или примени шаблон в разделе «Редактор расписания»."
TRAINER_SLOTS_ROW = "{date} {time_range} — {status}"
TRAINER_SLOTS_STATUS_AVAILABLE = "свободен"
TRAINER_SLOTS_STATUS_BOOKED = "занят"
TRAINER_SLOTS_STATUS_CANCELLED = "отменён"
TRAINER_SLOT_DELETED = "Слот удалён."
TRAINER_SLOT_CANNOT_DELETE_BOOKED = "Занятый слот нельзя удалить."

# Trainer: my bookings (grouped by day, nearest first; extra: service, arena, client, session number)
TRAINER_BOOKINGS_TITLE = "📋 <b>Мои записи</b>\n\nБлижайшие занятия сверху, по дням. В скобках: услуга, арена, клиент, какое занятие по счёту."
TRAINER_BOOKINGS_EMPTY = "Пока нет записей."
TRAINER_BOOKINGS_DAY_HEADER = "\n📅 <b>{date} ({day})</b>"
TRAINER_BOOKINGS_ROW_TIME_CLIENT = "{time} — {client_display}"
TRAINER_BOOKINGS_ROW_EXTRA = "   ({extra})"
TRAINER_BOOKINGS_ROW_COMMENT = "   Комментарий: {comment}"
TRAINER_BOOKINGS_SESSION_NTH = "{n}-е занятие"
TRAINER_BOOKINGS_BUTTON_WRITE = "✉️ Написать клиенту"
TRAINER_BOOKINGS_BUTTON_WRITE_SLOT = "✉️ Написать клиенту — {date} {time}"
TRAINER_BOOKINGS_BUTTON_CANCEL = "❌ Отменить запись"
TRAINER_BOOKINGS_CHOOSE_WRITE = "Выберите запись, чтобы написать клиенту:"
TRAINER_BOOKINGS_CHOOSE_CANCEL = "Какую запись отменить? Перед отменой предупредите клиента."
TRAINER_BOOKINGS_WRITE_LINK = "Запись {date} {time}. Написать клиенту в Telegram?"
TRAINER_BOOKINGS_BUTTON_BACK_TO_LIST = "◀️ К списку записей"
TRAINER_BOOKINGS_CANCEL_WARNING = (
    "⚠️ <b>Перед отменой обязательно предупредите клиента</b> (звонок или сообщение в Telegram).\n\n"
    "Отменить запись на <b>{date} ({day}) {time}</b>?"
)
TRAINER_BOOKINGS_CANCEL_CONFIRM_YES = "Да, отменить"
TRAINER_BOOKINGS_CANCEL_CONFIRM_NO = "Нет, вернуться"
TRAINER_BOOKINGS_CANCELLED = "Запись отменена. Слот снова свободен."
TRAINER_BOOKINGS_BUTTON_WRITE_LINK = "✉️ Написать в Telegram"
TRAINER_BOOKING_NOTIFICATION = (
    "🔔 <b>Новая запись!</b>\n\n"
    "{date} ({day}) {time}\n"
    "Телефон: {phone}\n"
    "Комментарий: {comment}\n\n"
    "Нажмите кнопку ниже, чтобы написать клиенту в Telegram."
)
TRAINER_BOOKING_NOTIFICATION_NO_COMMENT = (
    "🔔 <b>Новая запись!</b>\n\n"
    "{date} ({day}) {time}\n"
    "Телефон: {phone}\n\n"
    "Нажмите кнопку ниже, чтобы написать клиенту в Telegram."
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
ADMIN_STATS_SIGNAL_PENDING = "На модерации {n} тренер(ов) — /pending"
ADMIN_STATS_SIGNAL_REQUESTS_OPEN = "Заявок без отклика: {n} — клиенты ждут"
ADMIN_STATS_SIGNAL_REQUESTS_STALE = "Заявок без отклика дольше 7 дней: {n}"
ADMIN_STATS_SIGNAL_NO_BOOKINGS = "За 7 дней ни одной записи при {active} активных тренерах"
ADMIN_STATS_SIGNAL_LOW_CONVERSION = "Низкая конверсия заявка→отклик ({pct}%) за 30 дней"

# Shared (rate limit)
RATE_LIMIT_MESSAGE = "Слишком много запросов. Подождите минуту и попробуйте снова."
