# План: Welcome-ссылка (сертификат как онбординг)

Тренер регистрирует сертификат в системе и генерирует ссылку. Клиент (новый или существующий) переходит по ссылке → создаётся/находится клиент, привязывается сертификат, подставляются имя/телефон из сертификата, в сессии выставляются город/услуга/тренер по умолчанию. Один переход = полный онбординг.

---

## 1. Миграция: recipient_phone

- **Файл:** `migrations/versions/0059_certificate_recipient_phone.py`
- **Действие:** добавить в `certificate_instances` колонку `recipient_phone` (VARCHAR(32), nullable).
- **Модель:** в `CertificateInstance` добавить поле `recipient_phone`.

---

## 2. Бэкенд: сертификаты

### 2.1 issue_certificate

- Добавить параметр `recipient_phone: str | None = None`.
- При INSERT заполнять `recipient_phone` (нормализованный телефон или null).
- В RETURNING/ответе не обязательно возвращать phone (по желанию можно).

### 2.2 bind_certificate_to_client_by_code

- В SELECT добавить `recipient_name`, `recipient_phone`.
- Возвращать в dict: `recipient_name`, `recipient_phone` (чтобы бот мог обновить профиль клиента).
- Логика привязки без изменений (client_id, idempotent).

### 2.3 Обновление профиля клиента при привязке

- **Где:** в клиентском боте, после успешного `bind_certificate_to_client_by_code`.
- **Условие:** если в ответе есть `recipient_name` или `recipient_phone`, и у клиента пустые соответствующие поля — обновить клиента (first_name, last_name из recipient_name; phone из recipient_phone). Разбить recipient_name на первое слово = first_name, остальное = last_name (или целиком в first_name, если одно слово).
- **Кто обновляет:** вызов существующего `get_or_create_client` с передачей name/phone после привязки не подходит, т.к. клиент уже создан. Нужен отдельный вызов обновления: либо в `client_use_cases` функция `update_client_from_certificate(client_id, recipient_name, recipient_phone)`, либо один запрос в handler. Лучше: новая функция `apply_certificate_recipient_to_client(session, client_id, recipient_name, recipient_phone)` в client_use_cases: обновляет clients SET first_name, last_name, phone где id=client_id и (current first_name/last_name/phone пустые). Так не перезатираем уже заполненное.

### 2.4 Город и услуга по умолчанию (тренер)

- **Источник:** у тренера в профиле есть `trainer_profiles.city_id`; услуги — `trainer_services` (есть уже `get_first_service_id_for_trainer`).
- **Нужно:** функция `get_trainer_default_city_and_service(session, trainer_id) -> (city_id | None, service_id | None)` (или два отдельных запроса). Город из trainer_profiles.city_id, услуга — первый из trainer_services.
- **В боте:** после привязки сертификата, если есть `trainer_id`, вызвать получение city_id и service_id; затем `set_city`, `set_service`, `set_selected_trainer`. Так клиент попадает в каталог сразу с выбранным тренером, городом и услугой.

---

## 3. API

### 3.1 POST /trainer/certificate-issue

- В теле запроса добавить поле `recipient_phone: str | None = None`.
- Проброс в `issue_certificate(..., recipient_phone=...)`.
- Остальное без изменений (recipient_email, уведомление в бот и т.д.).

---

## 4. Клиентский бот: /start cert_<CODE>

Текущий поток:

1. get_or_create_client(telegram_id) → client_id
2. bind_certificate_to_client_by_code(session, code, client_id) → bound
3. Если bound: set_selected_trainer(telegram_id, trainer_id)

Дополнительно:

1. После bind: вызвать `apply_certificate_recipient_to_client(session, client_id, bound["recipient_name"], bound["recipient_phone"])` (если есть что подставлять).
2. Получить city_id, service_id для trainer_id (get_trainer_default_city_and_service или два запроса).
3. Вызвать set_city(telegram_id, city_id), set_service(telegram_id, service_id), set_selected_trainer(telegram_id, trainer_id) — только если city_id и service_id не null.
4. Ответ и кнопки без изменений.

---

## 5. UI тренера: «Создать welcome-ссылку»

### 5.1 Место

- В разделе «Сертификаты» (вкладка в trainer-pass-products.html) добавить кнопку **«Создать welcome-ссылку»** (рядом с «Выдать сертификат»).
- По нажатию открывается экран (новый экран или модальное состояние) с формой.

### 5.2 Поля формы

| Поле            | Обязательное | Куда сохраняется      | Примечание                          |
|-----------------|-------------|------------------------|-------------------------------------|
| Имя             | да          | recipient_name (часть) | Одна строка или два поля Имя/Фамилия |
| Фамилия         | нет         | recipient_name         | Или одно поле «Имя получателя»      |
| Телефон         | нет         | recipient_phone        | Для подстановки в профиль при входе |
| Номинал         | да          | certificate_product_id | Выбор продукта или «Любая сумма»   |
| Email           | нет         | recipient_email        | Отправить ссылку на почту           |

Удобный вариант: одно поле «Имя получателя» (как сейчас) + поле «Телефон» + выбор номинала + email. Имя можно разбивать на first/last при желании на бэкенде или хранить как есть в recipient_name.

### 5.3 Поведение

1. Тренер заполняет форму → отправка `POST /trainer/certificate-issue` с `recipient_name`, `recipient_phone`, `recipient_email`, `certificate_product_id` (client_id = null).
2. Ответ: код и данные сертификата. Собираем ссылку: `https://t.me/{client_bot_username}?start=cert_{code}_ref_{trainer_id}`.
3. На экране показать: «Готово. Отправьте клиенту ссылку:» + ссылка + кнопка «Скопировать ссылку». Опционально: «Отправить на email» (если заполнен email — уже отправлено при issue).
4. При желании можно не дублировать форму «Выдать сертификат», а добавить в неё поле «Телефон» и блок «Ссылка для приглашения» после выдачи (показ ссылки cert_XXX_ref_TID). Тогда «Создать welcome-ссылку» = та же форма с акцентом на «не привязывать к клиенту» и показ ссылки.

### 5.4 Упрощение

- Один экран «Создать welcome-ссылку»: Имя получателя, Телефон (необяз.), Номинал (продукт), Email (необяз.) → Выдать → Показать ссылку и кнопку «Скопировать». Без выбора клиента (client_id = null). Так тренер явно создаёт «пригласительную» ссылку.

---

## 6. Порядок реализации

1. Миграция 0059 + поле в модели CertificateInstance.
2. issue_certificate: параметр recipient_phone, сохранение в БД.
3. bind_certificate_to_client_by_code: возврат recipient_name, recipient_phone.
4. client_use_cases: apply_certificate_recipient_to_client(client_id, recipient_name, recipient_phone).
5. booking_use_cases или trainer_use_cases: get_trainer_default_city_and_service(trainer_id) → (city_id, service_id).
6. API: recipient_phone в теле certificate-issue.
7. Клиентский бот: после bind — применить recipient к клиенту, выставить city/service/trainer.
8. UI тренера: форма «Создать welcome-ссылку» (или расширение формы выдачи сертификата + показ ссылки).

---

## 7. Город/услуга по умолчанию — откуда брать

- **Город:** `SELECT city_id FROM trainer_profiles WHERE trainer_id = :tid` (один город у тренера в профиле). Может быть NULL.
- **Услуга:** уже есть `get_first_service_id_for_trainer(session, trainer_id)` — первый service_id из trainer_services.
- Если city_id нет — не вызываем set_city (клиент выберет сам или останется null). Если service_id нет — не вызываем set_service. Так не ломаем каталог.

---

## Реализовано

- **Миграция 0059** + поле `recipient_phone` в модели.
- **issue_certificate** — параметр `recipient_phone`, сохранение в БД.
- **bind_certificate_to_client_by_code** — возврат `recipient_name`, `recipient_phone`.
- **apply_certificate_recipient_to_client** в client_use_cases.
- **get_trainer_default_city_and_service** в booking_use_cases; бот после bind вызывает set_city/set_service/set_selected_trainer.
- **API:** в `CertificateIssueBody` добавлено `recipient_phone`; в ответе POST `/trainer/certificate-issue` при наличии `client_bot_username` в конфиге возвращается **welcome_link** (`https://t.me/{bot}?start=cert_{code}_ref_{trainer_id}`).
- **UI (trainer-pass-products):** в форме «Выдать сертификат» добавлено поле «Телефон получателя»; при выборе клиента подставляются имя и телефон; после выдачи показывается блок «Welcome-ссылка» с ссылкой и кнопкой «Скопировать ссылку». Город/услуга по умолчанию берутся из профиля тренера и первой услуги (см. п.7).
- **Отдельный экран «Создать welcome-ссылку»:** кнопка «🔗 Создать welcome-ссылку» во вкладке «Сертификаты»; экран только с выбором номинала (сертификата), без имени/телефона/email; вызов POST `/trainer/welcome-link/cert` → одноразовая ссылка + код сертификата.
- **Одноразовые ссылки (миграция 0060):** таблица `welcome_link_tokens` (id UUID, type cert|pass|generic, trainer_id, cert_code, pass_product_id, used_at). При генерации ссылки создаётся токен; ссылка вида `?start=welcome_t_{uuid}`. При первом входе токен сжигается (used_at=now()); повторный вход → «Ссылка уже использована или недействительна». Сертификаты и абонементы — только через токен; универсальная (Мои клиенты) — тоже через токен.
- **Welcome для абонементов:** кнопка во вкладке «Абонементы», выбор продукта → GET `/trainer/welcome-link/pass` → одноразовая ссылка. В «Мои клиенты» блок «Пригласить по ссылке» → GET `/trainer/welcome-link` → одноразовая ссылка.

---

## Оценка функционала welcome-ссылок

**Плюсы:**
- Удобно для тренера: одна ссылка вместо объяснения «открой бота, выбери город, услугу, меня».
- Онбординг в один тап: клиент попадает сразу к нужному тренеру с подставленными городом и услугой.
- Сертификат по ссылке решает кейс «подарил сертификат — человек перешёл и привязал».
- Одноразовость токенов снижает риск перепоста одной ссылки многим и даёт контроль (один переход = один клиент/один сертификат).

**Минусы и риски:**
- Ссылки длинные (UUID), не «красивые»; при желании можно добавить короткий домен + редирект.
- Если клиент перешёл по ссылке, но не завершил действие (закрыл бота), ссылка уже сожжена — тренеру нужно генерировать новую (для сертификата это означает новый выпуск).
- Нет срока действия токена: старые неиспользованные токены висят в БД (при желании можно добавить TTL и джоб очистки).
- Универсальная ссылка не передаёт контекст «на какой абонемент/сертификат» — только «приди к этому тренеру».

**Итог:** функционал полезен для онбординга и подарков-сертификатов; одноразовость — разумный компромисс между удобством и контролем. Для массовых рассылок «пригласи N человек» тренер генерирует N ссылок (или одну универсальную на человека).
