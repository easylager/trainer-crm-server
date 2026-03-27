"""
All user-facing bot messages. Clear names; no hardcoding in handlers.
Prefixes: client bot vs trainer bot.
"""

# --- Client bot ---
CLIENT_START_WELCOME = "Привет! Здесь можно найти тренера и записаться на занятие. Все разделы — в меню слева от поля ввода. Подробнее: /guide"
CLIENT_FALLBACK = "Используйте меню слева от поля ввода — там все разделы бота. Помощь: /guide"
CLIENT_CATALOG_LOADING = "Загружаю каталог тренеров..."
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

# Client: /guide (Помощь) — short, scannable; main menu is left of input
CLIENT_GUIDE = (
    "❓ <b>Помощь</b>\n\n"
    "Всё в <b>меню слева</b> от поля ввода.\n\n"
    "• <b>Тренеры и запись</b> — выберите город/услугу/арену, откройте карточку тренера: там слоты, «Записаться» и «Оставить заявку».\n"
    "• <b>Мои заявки</b> — ваши заявки и отклики тренеров.\n"
    "• <b>Мои записи</b> — ближайшие занятия; отмена — в разделе «Мои записи» или напишите тренеру.\n\n"
    "Не нашли ответ? Нажмите «Написать в поддержку» — мы ответим в этом чате."
)
CLIENT_SUPPORT_PROMPT = "Опишите ваш вопрос или проблему. Мы ответим здесь в чате."
CLIENT_SUPPORT_SENT = "Сообщение отправлено. Мы ответим вам в этом чате."

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
CLIENT_MY_REQUESTS_LIST_HINT = "Нажмите на заявку — откроются отклики тренеров: можно написать или записаться."
CLIENT_MY_REQUESTS_EMPTY = "У вас пока нет заявок. Оставьте заявку в каталоге тренеров (пустой список / низ списка / карточка тренера)."
CLIENT_MY_REQUESTS_BUTTON_LABEL = "{city}, {service}"
CLIENT_MY_REQUESTS_ROW = "{index}. 📍 {city}, {service}. {comment}"
CLIENT_MY_REQUESTS_ROW_NO_COMMENT = "{index}. 📍 {city}, {service}"
CLIENT_MY_REQUESTS_RESPONSES_HEADER = "Откликнулись ({count}):"
CLIENT_RESPONDER_LINE = "• {name}: {comment}"
CLIENT_RESPONDER_LINE_NO_COMMENT = "• {name}"
CLIENT_TRAINER_COMMENT_LABEL = "💬 Комментарий тренера: {comment}"
CLIENT_MY_REQUESTS_PAGE_PREV = "◀ Предыдущие"
CLIENT_MY_REQUESTS_PAGE_NEXT = "Следующие ▶"
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
TRAINER_REQUESTS_FILTER_LINE = "По вашему городу и услугам из профиля."
TRAINER_REQUESTS_EMPTY = "Пока нет заявок по вашему профилю (город + услуги). Заполните профиль на сайте."
TRAINER_REQUESTS_SECTION_NEW = "📥 <b>Новые</b> — откликнитесь, клиент увидит вас в списке."
TRAINER_REQUESTS_SECTION_IN_PROGRESS = "✓ <b>В работе</b> — вы откликнулись, можно записать клиента на слот."
TRAINER_REQUESTS_SECTION_NEW_EMPTY = "📥 Новых заявок нет."
TRAINER_REQUESTS_SECTION_IN_PROGRESS_EMPTY = "✓ В работе заявок нет."
TRAINER_REQUESTS_PAGE_BACK = "◀ Назад"
TRAINER_REQUESTS_PAGE_NEXT = "Далее ▶"
# Detail screen (one request)
TRAINER_REQUEST_DETAIL_HEAD = "<b>{city}</b>  ·  <b>{service}</b>"
TRAINER_REQUEST_DETAIL_COMMENT = "💬 Комментарий клиента: {comment}"
TRAINER_REQUEST_DETAIL_RESPONDED_HINT = (
    "Вы уже откликнулись на эту заявку. Клиент видит вас в списке откликнувшихся."
)
TRAINER_REQUEST_ROW = "{index}. {city}, {service}. {comment}"
TRAINER_REQUEST_ROW_NO_COMMENT = "{index}. {city}, {service}"
TRAINER_BUTTON_REQUESTS = "📋 Заявки клиентов"
TRAINER_BUTTON_RESPOND = "✅ Готов взять"
TRAINER_BUTTON_RESPOND_INDEX = "{index}. Готов взять"
TRAINER_RESPONDED = "Вы откликнулись"
TRAINER_RESPONDED_INDEX = "{index}. Вы откликнулись"
TRAINER_REQUESTS_BACK_TO_LIST = "◀️ К списку заявок"
TRAINER_REQUEST_WRITE_CLIENT = "✉️ Написать клиенту"
TRAINER_REQUEST_BOOK_CLIENT = "Записать клиента"
TRAINER_REQUEST_REMIND_WHEN_SLOTS = "Напомнить когда появятся слоты"
TRAINER_REQUEST_REMIND_SLOTS_SET = "Напомним, когда появятся свободные слоты — запишите клиента по этой заявке."
TRAINER_REQUEST_BOOK_CHOOSE_SLOT = "Выберите слот для записи клиента по заявке:"
TRAINER_REQUEST_BOOK_SUCCESS = "Клиент записан. Заявка закрыта, клиенту отправлено уведомление."
TRAINER_REQUEST_REMIND_HAS_SLOTS = "У вас заявка в работе — клиент ждёт записи. Есть свободные слоты: запишите его."
TRAINER_PENDING_BOOKING_REMINDER = (
    "У вас {count} {requests_word}: клиент ждёт записи с вашей стороны. "
    "Откройте «Заявки клиентов» — там можно оформить запись."
)
CLIENT_TRAINER_BOOKED_YOU = (
    "Вас записал тренер <b>{name}</b> на <b>{date}</b> ({day}) {time}.\n\n"
    "Детали, адрес и отмена — в <b>«Мои записи»</b> в меню бота."
)
TRAINER_RESPOND_SUCCESS = "Вы откликнулись на заявку. Клиент увидит вас в списке и сможет записаться или написать."
TRAINER_RESPOND_PROMPT_COMMENT = (
    "Напишите комментарий для клиента (необязательно).\n\n"
    "Например: <i>Когда появится слот на это время — запишу вас</i> или <i>Могу предложить Ср 18:00, Пт 19:00</i>.\n\n"
    "Клиент увидит это в откликах. Или нажмите «Отправить без комментария»."
)
TRAINER_RESPOND_SKIP = "Отправить без комментария"
TRAINER_BUTTON_DECLINE = "❌ Отклонить"
TRAINER_REQUEST_DECLINED = "Вы отклонили эту заявку. Она больше не отображается в списке."

# --- Notifications ---
TRAINER_DAILY_REQUESTS_REMINDER = (
    "Добрый день! По вашим услугам и городу сейчас открыто {count} {requests_word} от клиентов. "
    "Загляните в раздел «Заявки клиентов» — откликнитесь, и клиент сможет записаться к вам или написать."
)
TRAINER_REQUEST_NOTIFICATION = (
    "📩 <b>Новая заявка клиента</b>\n\n"
    "{city}, {service}\n"
    "Комментарий: {comment}\n\n"
    "Список заявок вы можете посмотреть в меню бота."
)
TRAINER_REQUEST_NOTIFICATION_NO_COMMENT = (
    "📩 <b>Новая заявка клиента</b>\n\n"
    "{city}, {service}\n\n"
    "Список заявок вы можете посмотреть в меню бота."
)
CLIENT_RESPONSE_NOTIFICATION = (
    "📩 По вашей заявке откликнулся тренер.\n\n"
    "Нажмите кнопку ниже — откроются отклики: можно написать тренеру или записаться к нему."
)
CLIENT_RESPONSE_NOTIFICATION_WITH_COMMENT = (
    "📩 По вашей заявке откликнулся тренер.\n\n"
    "💬 <b>{responder_name}</b>: {comment}\n\n"
    "Нажмите кнопку ниже — откроются все отклики: можно написать тренеру или записаться к нему."
)
CLIENT_RESPONSE_BUTTON_VIEW = "👤 Посмотреть отклики"
CLIENT_NO_RESPONSE_REMINDER = (
    "Пока по вашей заявке никто не откликнулся — мы ещё раз напомнили тренерам. "
    "Параллельно можете сами посмотреть тренеров в каталоге и записаться к тому, кто подойдёт. "
    "Если появятся отклики — мы сразу напишем."
)
CLIENT_BOOKING_CANCELLED_BY_TRAINER = (
    "⚠️ Тренер отменил запись на <b>{date}</b> ({day}) в {time}.\n\n"
    "Можете выбрать другое время или другого тренера: /book или «Настройки» → каталог."
)
CLIENT_BOOKING_CONFIRMED_BY_TRAINER = (
    "✅ Тренер подтвердил занятие <b>{date}</b> ({day}) {time}.\n\n"
    "Тренер: {trainer_name}."
)
CLIENT_BOOKING_DECLINED_BY_TRAINER = (
    "⚠️ Тренер отклонил запись на <b>{date}</b> ({day}) {time}.\n"
    "Причина: {reason}\n\n"
    "Вы можете выбрать другое время или другого тренера в каталоге."
)
CLIENT_PASS_ISSUED = (
    "🎫 Вам выдан абонемент: <b>{product_name}</b> — {sessions_total} занятий.\n"
    "Осталось: {sessions_remaining}. Тренер: {trainer_name}."
)
CLIENT_BUTTON_MY_PASSES = "Мои абонементы"
CLIENT_CERTIFICATE_ISSUED = (
    "🎁 Вам выдан сертификат на <b>{amount_display}</b>. Код: <code>{code}</code>. Тренер: {trainer_name}."
)
CLIENT_BUTTON_MY_CERTIFICATES = "Мои сертификаты"
# Единое мини-приложение: абонементы + сертификаты (вкладки).
CLIENT_MENU_PASSES_CERTIFICATES_DESC = "Мои Абонементы/ Сертификаты"
CLIENT_BUTTON_MY_PASSES_AND_CERTIFICATES = "Мои Абонементы/Сертификаты"
CLIENT_MY_PASSES_AND_CERTIFICATES_INTRO = (
    "📦 Абонементы — остаток занятий, тренер, срок. "
    "🎁 Сертификаты — код, номинал, активация. Нажмите кнопку ниже."
)
CLIENT_CERT_BOUND = "Сертификат привязан к вашему аккаунту. Можете записаться к тренеру или посмотреть сертификаты."
# Generic / pass invite links (no cert)
CLIENT_WELCOME_REF = "Добро пожаловать! Тренер пригласил вас. Запишитесь на занятие или выберите другого тренера."
CLIENT_PASS_WELCOME = "Тренер {name} пригласил вас. Можете записаться на занятие или купить абонемент."
CLIENT_BUTTON_BUY_PASS = "Купить абонемент"
CLIENT_WELCOME_LINK_USED = "Эта ссылка уже использована или недействительна. Попросите тренера прислать новую ссылку."
CLIENT_CERT_CODE_INVALID = "Код сертификата не найден или уже использован другим пользователем. Проверьте ссылку или обратитесь к тренеру."
CLIENT_MY_CERTIFICATES_INTRO = "🎁 Ваши сертификаты: номинал, код, статус. Нажмите кнопку ниже."
# Reminders: fixed date/time (no "через" — notifications may be delayed by poll interval).
CLIENT_REMINDER_24H = (
    "⏰ Напоминаем: у вас занятие <b>{date}</b> ({day}) в {time}, {duration} мин.\n\n"
    "Чтобы уточнить детали или адрес — зайдите в «Мои записи» в меню бота."
)
CLIENT_REMINDER_2H = (
    "⏰ Напоминаем: у вас занятие <b>{date}</b> ({day}) в {time}, {duration} мин.\n\n"
    "Чтобы уточнить детали или адрес — зайдите в «Мои записи» в меню бота."
)
CLIENT_BOOKING_COMPLETED = (
    "✅ Занятие <b>{date}</b> ({day}) {time} завершено.\n\n"
    "Поделитесь впечатлениями — поставьте оценку тренеру и при желании напишите отзыв."
)
# Inactive: 10 / 30 days since last session — friendly nudge to book again (once per client per kind)
CLIENT_INACTIVE_10_DAYS = (
    "Привет{name}! 👋✨\n\n"
    "Мы заметили, что с прошлого занятия прошло уже больше недели. "
    "Как насчёт снова выделить время для себя? 💪 Занятия помогают держать форму и настроение на высоте.\n\n"
    "Выберите тренера и удобное время — мы всегда рады видеть вас! 😊"
)
CLIENT_INACTIVE_30_DAYS = (
    "Привет{name}! 🌟😊\n\n"
    "Прошёл уже месяц с вашего последнего занятия — мы по вам скучаем! "
    "Возвращайтесь, когда будет удобно: тренеры и слоты ждут. "
    "Один шаг к каталогу — и вы снова в деле. Удачи! 💪✨"
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
    "Появилось окно на <b>{date}</b> ({day}) {time} у тренера <b>{trainer_name}</b>. Записаться?"
)
CLIENT_BUTTON_BOOK_THIS_SLOT = "Записаться"
CLIENT_FEEDBACK_RATE_PROMPT = "Поставьте оценку тренеру от 1 до 5 звёзд:"
CLIENT_FEEDBACK_REVIEW_PROMPT = "Напишите отзыв (необязательно) или нажмите «Пропустить»:"
CLIENT_FEEDBACK_SKIP = "Пропустить"
CLIENT_FEEDBACK_THANKS = "Спасибо за отзыв!"
TRAINER_BOOKING_COMPLETED = (
    "✅ Занятие <b>{date}</b> ({day}) {time} завершено.\n\n"
    "Поделитесь впечатлениями (необязательно)."
)
TRAINER_NO_PASS_FOR_SERVICE = (
    "ℹ️ У клиента нет абонемента по этой услуге. Занятие проведено без списания.\n"
    "Клиент: {client_name}. {date} {time}. Услуга: {service_name}."
)
TRAINER_BUTTON_LEAVE_FEEDBACK = "✍️ Оставить отзыв"
TRAINER_FEEDBACK_PROMPT = "Напишите отзыв о занятии (необязательно, можно коротко):"
TRAINER_FEEDBACK_THANKS = "Спасибо! Отзыв сохранён."
TRAINER_START_WELCOME = (
    "Привет!\n\n"
    "Ты в боте как тренер. Дальше — <b>меню слева от поля ввода</b>: расписание, заявки, записи, клиенты.\n\n"
    "Коротко по разделам: /guide"
)
TRAINER_ONLY_VIA_SITE = "Этот бот только для тренеров. Подключение по ссылке с сайта после регистрации и оплаты."
# После привязки по ссылке: без обещания полного меню (гейт может быть закрыт).
TRAINER_LINK_SUCCESS = (
    "Аккаунт привязан к этому Telegram.\n\n"
    "Статус и анкета: <b>/profile</b>. Помощь: /guide"
)
# Только если тренер уже active — честно про все пункты меню.
TRAINER_LINK_SUCCESS_ACTIVE = (
    "Аккаунт привязан.\n\n"
    "Разделы тренера — в <b>меню слева</b>: расписание, заявки, записи, клиенты. Помощь: /guide"
)
TRAINER_LINK_INVALID = "Ссылка недействительна или уже использована. Получи новую на сайте после оплаты."
TRAINER_FALLBACK = "Используйте меню слева от поля ввода — там все разделы. Помощь: /guide"

# Trainer: errors and hints
TRAINER_ERROR_BOOKING_NOT_FOUND = "Запись не найдена. Обновите «Моё расписание» в приложении."
TRAINER_ERROR_CANCEL_FAILED = "Не удалось отменить запись (уже отменена или не найдена). Обновите расписание в приложении."
TRAINER_ERROR_BOOKING_CLOSED_OR_NOT_FOUND = "Запись не найдена или уже закрыта. Откройте «Моё расписание» в приложении снова."
TRAINER_ERROR_FEEDBACK_SAVE_FAILED = "Не удалось сохранить отзыв. Попробуйте ещё раз или пропустите."
TRAINER_ERROR_RESPOND_FAILED = "Не удалось откликнуться (заявка уже закрыта или вы уже откликались). Обновите «Заявки клиентов»."
TRAINER_ERROR_NO_SERVICES = (
    "У тебя не указана ни одна услуга. Добавь услугу в профиле: /profile (Mini App при HTTPS) или личный кабинет на сайте."
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
    "Открой расписание — шаблон недели, календарь слотов и применение на неделю. "
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

# Trainer: /guide — short, scannable; main menu is left of input
TRAINER_GUIDE = (
    "❓ <b>Помощь (тренер)</b>\n\n"
    "Всё в <b>меню слева</b> от поля ввода.\n\n"
    "• <b>Расписание</b> — шаблон недели, календарь слотов и применение на неделю. По клику на свободный слот можно записать клиента.\n"
    "• <b>Заявки клиентов</b> — заявки по городу и услугам. Отклик — клиент увидит вас и сможет записаться.\n"
    "• <b>Моё расписание</b> (мини-приложение из раздела «Расписание») — свободные и занятые слоты; по занятому слоту — запись клиента, подтверждение, отмена, «проведено».\n"
    "• <b>Статистика</b> — занятия, загрузка, новые клиенты, рейтинг.\n\n"
    "Клиентов из лички переведите в бота: <b>/invite</b> или кнопка «Пригласить клиента» ниже — готовый текст со ссылками.\n\n"
    "Анкета и фото: <b>/profile</b> — кнопка открывает <b>Mini App</b> (нужен HTTPS в продакшене). "
    "Вопрос или проблема? Нажмите «Написать в поддержку» — мы ответим в этом чате."
)
TRAINER_SUPPORT_PROMPT = "Опишите ваш вопрос или проблему. Мы ответим здесь в чате."
TRAINER_SUPPORT_SENT = "Сообщение отправлено. Мы ответим вам в этом чате."

# Trainer: invite clients from DM → client bot deep link + catalog URL (see trainer_invite_links.py)
TRAINER_INVITE_BUTTON = "📣 Пригласить клиента"
TRAINER_INVITE_INTRO_HTML = (
    "📣 <b>Пригласить клиента</b>\n\n"
    "Чтобы перевести переписку из Direct в продукт: <b>перешлите клиенту следующее сообщение</b> целиком "
    "или скопируйте из него текст.\n\n"
    "<i>Первая ссылка — вход в клиентский бот сразу на ваш профиль. Вторая — страница каталога "
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
    "Укажите в <b>/profile</b> или в кабинете на сайте и снова нажмите «Пригласить клиента»."
)

# Trainer: access gate (until profile complete + moderation approved)
# Tone: «ты», коротко; без дублирования тревоги между /start, middleware и /profile.
TRAINER_GATE_CALLBACK_BLOCKED = (
    "Этот раздел пока закрыт. Сначала заполни анкету и дождись одобрения — /profile."
)
TRAINER_GATE_BLOCKED_PROFILE = (
    "Расписание, заявки и записи закрыты: в анкете не хватает обязательных полей.\n\n"
    "Открой <b>/profile</b> — там видно, что добить. Текущий статус: <b>/profile</b>."
)
# Полная анкета, но ещё не нажата отправка на модерацию (moderation_submitted_at пустой).
TRAINER_GATE_INVITE_SUBMIT = (
    "Анкета заполнена. Осталось отправить её на проверку: <b>/profile</b> → "
    "«Готово — отправить на модерацию».\n\n"
    "После отправки модератор посмотрит профиль; обычно ответ в течение рабочего дня. Статус: /profile"
)
# Анкета отправлена, ждём модератора (без комментария «нужны правки»).
TRAINER_GATE_PENDING_MODERATION = (
    "Анкета на проверке. Ничего делать не нужно — дождись решения. "
    "Когда одобрят, разделы откроются сами. Статус: /profile"
)
# Комментарий модератора при «нужны правки» (moderation_feedback).
TRAINER_GATE_NEEDS_EDIT = (
    "Нужны правки по анкете.\n\n"
    "<b>Комментарий модератора:</b>\n{feedback}\n\n"
    "Исправь в <b>/profile</b> или в личном кабинете на сайте и снова отправь на модерацию."
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
    "Вам открыт доступ к функционалу бота. Можно приступать к работе."
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
TRAINER_CANCEL_IDLE = "Нечего отменять. Профиль: /profile."

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
ADMIN_NEEDS_EDIT_PROMPT = "Напишите текст фидбека для тренера (он увидит его в личном кабинете на сайте):"
ADMIN_NEEDS_EDIT_DONE = "Фидбек сохранён. Тренер остаётся в статусе «на модерации» и увидит текст на сайте."
ADMIN_NEEDS_EDIT_CANCELLED = "Отменено."
TRAINER_EDUCATION_MODERATION_APPROVED = (
    "✅ Раздел «Образование» в твоём профиле прошёл модерацию."
)
TRAINER_EDUCATION_MODERATION_REJECTED = (
    "⚠️ Раздел «Образование» отправлен на доработку.\n\nКомментарий модератора:\n{reason}"
)

# Trainer schedule (by calendar week + template for quick apply)
TRAINER_BUTTON_SCHEDULE = "📅 Расписание"
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
TRAINER_BUTTON_MY_SLOTS = "📋 Мое расписание"
# Text for the main menu button (left of input) when it opens Web App schedule
TRAINER_MENU_SCHEDULE_WEBAPP = "Расписание"
# Short message when /schedule or menu opens Web App (one button below)
TRAINER_SCHEDULE_OPEN_WEBAPP = "📋 Нажмите кнопку ниже, чтобы открыть расписание в приложении."
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
TRAINER_SCHEDULE_GENERATED = "Расписание на неделю заменено. Создано слотов: {count}. Посмотреть: «Мое расписание»."
TRAINER_SCHEDULE_GENERATED_NONE = "Расписание на неделю заменено. В шаблоне нет слотов на эти дни — неделя очищена от свободных слотов."
TRAINER_SCHEDULE_DELETED = "Слот удалён из шаблона."
TRAINER_BUTTON_CREATE_BOOKING = "➕ Создать запись"
TRAINER_CREATE_BOOKING_NO_SLOTS = (
    "Нет свободных слотов в ближайшие 14 дней (начиная примерно через 2 часа).\n\n"
    "Добавьте свободные слоты в расписании и попробуйте ещё раз."
)
TRAINER_CREATE_BOOKING_CHOOSE_SLOT = "Выбери свободный слот, на который хочешь записать клиента:"
TRAINER_CREATE_BOOKING_NO_CLIENTS = (
    "Пока в системе нет клиентов, с которыми вы уже проводили занятия.\n\n"
    "Когда появятся первые записи, вы сможете быстро записывать их на новые слоты из этого экрана."
)
TRAINER_CREATE_BOOKING_CHOOSE_CLIENT = (
    "Кого записать на <b>{date}</b> ({day}) {time}? Выбери клиента из списка:"
)
TRAINER_CREATE_BOOKING_DONE = (
    "✅ Записали клиента <b>{client_name}</b> на <b>{date}</b> ({day}) {time}."
)
TRAINER_CREATE_BOOKING_SLOT_UNAVAILABLE = (
    "Слот уже недоступен (кто-то его занял или он был удалён). Обновите расписание и попробуйте снова."
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
TRAINER_BOOKINGS_LIST_HINT = "Нажмите на запись — откроются детали и кнопки «Написать» / «Отменить»."
TRAINER_BOOKINGS_EMPTY = "Пока нет записей."
TRAINER_BOOKINGS_DAY_EMPTY = "На этот день записей нет."
TRAINER_BOOKINGS_PAGE_BACK = "◀ Предыдущий день"
TRAINER_BOOKINGS_PAGE_NEXT = "Следующий день ▶"
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
    "⚠️ Клиент <b>{client_name}</b> отменил запись на <b>{date}</b> ({day}) в {time}.\n"
    "Причина: {reason}"
)
TRAINER_BOOKING_CANCELLED_BY_CLIENT_NO_REASON = (
    "⚠️ Клиент <b>{client_name}</b> отменил запись на <b>{date}</b> ({day}) в {time}."
)
TRAINER_BOOKINGS_BUTTON_DECLINE = "❌ Отклонить"
TRAINER_BOOKINGS_BUTTON_MAKE_REGULAR = "📅 Сделать постоянным клиентом"
TRAINER_BOOKINGS_BUTTON_REMOVE_REGULARITY = "📅 Снять регулярность"
TRAINER_RECURRING_DONE = "Клиент закреплён как постоянный: каждую неделю в это время слот будет автоматически бронироваться за ним."
TRAINER_RECURRING_REMOVED = "Регулярность снята."
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
    "📅 {date} ({day}) {time}\n\n"
    "👤 <b>Клиент:</b> {client_name}\n"
    "📱 Телефон: {phone}\n"
    "🎯 Услуга: {service}\n"
    "📍 Город: {city}\n"
    "🏟 Арены: {arenas}\n"
    "💬 Комментарий: {comment}\n\n"
    "Подтвердите или отклоните запись кнопками ниже. Можно написать клиенту в Telegram.\n\n"
    "💡 Клиент записался через бота — слот уже занят в расписании, напоминания ему придут автоматически."
)
TRAINER_BOOKING_NOTIFICATION_NO_COMMENT = (
    "🔔 <b>Новая запись!</b>\n\n"
    "📅 {date} ({day}) {time}\n\n"
    "👤 <b>Клиент:</b> {client_name}\n"
    "📱 Телефон: {phone}\n"
    "🎯 Услуга: {service}\n"
    "📍 Город: {city}\n"
    "🏟 Арены: {arenas}\n\n"
    "Подтвердите или отклоните запись кнопками ниже. Можно написать клиенту в Telegram.\n\n"
    "💡 Клиент записался через бота — слот уже занят в расписании, напоминания ему придут автоматически."
)
TRAINER_BOOKING_CONFIRMED = (
    "Запись подтверждена.\n\n"
    "Клиент: {client_display}\n"
    "Дата и время: {date} ({day}) {time}"
)
TRAINER_BOOKING_DECLINE_PROMPT = (
    "Напишите короткий комментарий, почему не получается провести это занятие.\n\n"
    "Комментарий <b>обязателен</b> — клиент увидит его в уведомлении об отказе."
)
TRAINER_BOOKING_DECLINE_COMMENT_REQUIRED = (
    "Комментарий обязателен. Напишите причину отклонения для клиента (пустое сообщение не подойдёт)."
)
TRAINER_BOOKING_DECLINED_DONE = "Запись отклонена, клиенту отправлено сообщение с причиной."
TRAINER_BOOKING_CONFIRM_REMINDER = (
    "⏰ Через 2 часа занятие с {client_display} — <b>{date}</b> ({day}) {time}.\n\n"
    "Подтвердите или отклоните запись, чтобы клиент точно понимал свой статус."
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
TRAINER_STATS_OPEN_APP = "📊 Откройте статистику в приложении — там графики, тренды и инсайты по вашей работе."
TRAINER_BUTTON_STATS_APP = "📊 Открыть статистику"
TRAINER_SUBSCRIPTION_REMINDER = (
    "Подписка заканчивается <b>{expires_date}</b>. "
    "Оплатите до этой даты (можно заранее) — иначе доступ к каталогу и записям будет приостановлен."
)
TRAINER_BUTTON_PAY_SUBSCRIPTION = "Оплатить подписку"
# /subscription — конструктор тарифов (мини-апп trainer-subscription)
TRAINER_BUTTON_SUBSCRIPTION_CONSTRUCTOR = "🧩 Открыть конструктор подписки"
TRAINER_SUBSCRIPTION_CONSTRUCTOR_HINT = (
    "В конструкторе вы выбираете <b>уровень</b> (CRM → Онлайн-запись → Аналитика): каждый следующий включает предыдущий. "
    "Там же видно цену за период и можно оформить демо-активацию."
)
TRAINER_SUBSCRIPTION_WITH_TIER = (
    "📋 <b>Подписка</b>\n\n"
    "Текущий уровень: <b>{tier_name}</b>\n"
    "Действует до: <b>{expires_date}</b>\n\n"
    "{hint}"
)
TRAINER_SUBSCRIPTION_WITHOUT_TIER = (
    "📋 <b>Подписка</b>\n\n"
    "Сейчас нет активного тарифа по уровням или срок истёк.\n\n"
    "{hint}"
)
TRAINER_SUBSCRIPTION_ACTIVE = (
    "Подписка на платформу активна до <b>{expires_date}</b>. Вы в каталоге.\n\n"
    "Кнопка ниже — оплата за <b>следующий период</b> (после этой даты). Можно выбрать срок: месяц, 3 мес, год или 1,5 года."
)
TRAINER_SUBSCRIPTION_EXPIRED = (
    "Подписка истекла. Оплатите за новый период (месяц / 3 мес / год / 1,5 года), чтобы снова быть в каталоге."
)

# Subscription tier access messages
TRAINER_TIER_REQUIRED_CRM = (
    "⚠️ Для этой функции нужна подписка уровня <b>CRM</b> или выше.\n\n"
    "Оформите подписку, чтобы использовать расписание, клиентскую базу, абонементы и сертификаты."
)
TRAINER_TIER_REQUIRED_ONLINE = (
    "⚠️ Для онлайн-записи клиентов нужна подписка уровня <b>Онлайн-запись</b> или выше.\n\n"
    "С этим уровнем клиенты смогут записываться к вам через каталог самостоятельно."
)
TRAINER_TIER_REQUIRED_ANALYTICS = (
    "⚠️ Для аналитики нужна подписка уровня <b>Аналитика</b>.\n\n"
    "С этим уровнем вам доступны отчёты, статистика и выгрузка данных."
)
TRAINER_TIER_CTA = "Оформите подписку в разделе ниже 👇"
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
