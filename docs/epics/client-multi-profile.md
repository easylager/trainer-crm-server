# EPIC1 — Клиент управляет несколькими профилями (дети + себя) из одного аккаунта

**Дата создания:** 2026-09-04
**Основание:** [DECISION-multi-profile-clients.md](./DECISION-multi-profile-clients.md) — там домен, альтернативы и почему именно так.
**Не путать с:** [PLAN-CLIENT-GROWTH-2026.md](./PLAN-CLIENT-GROWTH-2026.md) — тот план описывал этот же кусок как «E1.2 родитель с несколькими детьми», помеченный там как снятый из Фазы 1 («таких пользователей нет»). Это больше не так — эпик заменяет собой ту пометку.

## Цель одним предложением

Разделить «кто залогинен» (Telegram-аккаунт) и «кому оказывается услуга» (профиль: ребёнок или сам взрослый), не трогая коммерческую часть системы (брони, абонементы, сертификаты, заметки тренера уже ключуются по `client_id` и не мигрируют).

## Что НЕ входит в этот эпик

* Мультиучастники одной брони («ребёнок + родитель со скидкой» в одном слоте) — отдельная, более рискованная задача (`bookings.companion_client_id`), см. §7 решения. Делать отдельным эпиком после этого.
* Изменение `client_family_access_members` (второй телеграм видит того же ребёнка) — работает, не трогаем.
* Полноценная переработка UI хаба/каталога под мультипрофиль дальше переключателя — только необходимый минимум для корректности данных.

---

## Слайсы

### Слайс 1 — Схема: `client_profile_links` + автобэкофилл `self`
**Статус:** DONE

* Alembic-миграция: новая таблица `client_profile_links(account_telegram_id, profile_client_id, role, is_default)`, уникальность `(account_telegram_id, profile_client_id)`.
* Бэкофилл: для каждой существующей `clients.telegram_id IS NOT NULL` — строка `role='self', is_default=true`. Идемпотентно (`ON CONFLICT DO NOTHING`), безопасно перезапускать.
* SQLAlchemy-модель `ClientProfileLink` рядом с `ClientFamilyAccessMember`.

**Acceptance:** миграция применяется на локальной БД без ошибок; после применения `SELECT COUNT(*) FROM client_profile_links` = числу клиентов с `telegram_id IS NOT NULL` на момент миграции.

### Слайс 2 — Use-cases: разрешение и создание профилей
**Статус:** DONE

Новый модуль `src/application/client_profile_use_cases.py`:
* `resolve_acting_client_id(session, account_telegram_id, requested_profile_id=None)` — центральная точка. Без `requested_profile_id` ведёт себя **тождественно** сегодняшнему `get_client_id_by_telegram_id` (обратная совместимость), лениво создавая/чиня `self`-связь, если её почему-то нет (защита от гонок и от клиентов, созданных до слайса 1). С `requested_profile_id` — проверяет доступ через `client_profile_links` и требует активный статус.
* `list_accessible_profiles(session, account_telegram_id)` — все профили аккаунта с ролью и `is_default`, для переключателя в UI.
* `create_guardian_profile(session, account_telegram_id, first_name, last_name)` — новая `clients`-строка (`telegram_id=NULL`), связь `role='guardian'`.
* `set_default_profile(session, account_telegram_id, profile_client_id)`.

**Acceptance:** юнит-тесты на все четыре функции, включая: доступ к чужому профилю отклоняется; повторный вызов `resolve_acting_client_id` без профиля для старого (домиграционного) клиента возвращает тот же `client_id`, что и раньше.

### Слайс 3 — Endpoint для создания/списка профилей
**Статус:** DONE

* `GET /api/webapp/client/profiles` — список профилей аккаунта (`items`, `default_profile_id`).
* `POST /api/webapp/client/profiles` — создать профиль ребёнка (`first_name`, `last_name`), телефон подтягивается с аккаунта.
* `PATCH /api/webapp/client/profiles/{id}/default` — сделать профилем по умолчанию; чужой профиль → 404.

**Найден и исправлен баг при реализации** (не в исходном плане): `_ensure_self_link` создавала `self`-связь с жёстко заданным `is_default=true`, что при отложенном (ленивом) создании — после того как гостевой профиль уже сделан профилем по умолчанию — порождало **вторую** запись с `is_default=true` и переключатель тихо показывал не тот профиль. Исправлено: `is_default` теперь вычисляется (`NOT EXISTS` уже дефолтного профиля у аккаунта), а не задаётся жёстко. Плюс добавлен аппаратный инвариант — частичный уникальный индекс `uq_client_profile_links_one_default_per_account` (`UNIQUE (account_telegram_id) WHERE is_default`), чтобы такой класс багов ловился constraint violation, а не тихо портил данные. Оба сценария закрыты регрессионными тестами.

**Заголовок `X-Profile-Id`** для существующих клиентских эндпоинтов — перенесён в Слайс 4 вместе с их переключением (естественная зависимость, добавлять его раньше некуда его подключать).

**Acceptance:** 15 тестов (`tests/application/test_client_profile_use_cases.py`, `tests/api/test_client_profiles_endpoints.py`) — зелёные.

### Слайс 4 — Переключить существующие клиентские эндпоинты на `resolve_acting_client_id`
**Статус:** DONE (с осознанно суженным периметром — см. ниже)

Заголовок `X-Profile-Id` (опциональный, парсится нестрого — мусор/чужой id тихо деградирует к своему профилю через `resolve_acting_client_id`) добавлен и подключён в эндпоинтах, где резолюция `client_id` происходит непосредственно в `webapp.py`:
`GET /client/slots` (daypart-фильтр), `POST /client/booking`, `GET /client/session` (подсказка service_id), `POST /client/request`, `GET/POST` pass/cert-order request, `GET /client/activity-stats`, `GET /client/hub/bootstrap` (только `activity`/`passes` — см. ниже), `GET /client/passes`, `GET /client/certificates`, `POST /client/certificates/activate`, `PATCH /client/requests/{id}`, `POST /client/collective-session-booking`, `POST /client/collective-pass-order/request`.

При реализации нашёлся и исправлен баг **вне исходного плана**: `PATCH /client/requests/{id}` резолвил `client_id` через профиль для проверки владения, но передавал дальше в `replace_client_request_with_new`/`list_my_requests_with_responses` сырой `telegram_id` — те функции сами заново резолвили его в **свой** (self) client_id, поэтому редактирование заявки ребёнка от имени профиля-ребёнка молча возвращало 404. Исправлено добавлением опционального `acting_client_id` в обе функции (Telegram-бот, который зовёт их без профиля, не затронут). Закрыто регрессионным тестом.

**Осознанно не переключено** (задокументировано в коде):
* `POST/PATCH /client/family-access/*` — доступ семьи это свойство аккаунта, а не выбранного профиля.
* `POST /client/self-register` — регистрационный флоу, концепции профиля ещё не существует.
* `_bookings`/`_requests` внутри `GET /client/hub/bootstrap`, а также `GET /client/requests`, `GET /client/bookings(-history)`, `GET /client/collective-passes`, основной список `GET /client/slots` — резолвят `client_id`/`telegram_id` глубже, в других модулях (`client_session_use_cases.py`, `client_booking_use_cases.py` и т.п.), а не в `webapp.py` напрямую. Это осталось на будущий проход: пока переключатель профиля стоит на «ребёнке», хаб и списки записей всё ещё покажут данные аккаунта (родителя). (`_hub_session` — сохранённый/основной тренер — теперь профиль-осведомлён, см. Слайс 5; booking-history-часть внутри него всё ещё общая на аккаунт.)

Тесты: `tests/api/test_client_profile_switching_slice4.py` (4 теста — passes изолированы по профилю, заявка создаётся под выбранным профилем, PATCH уважает владение выбранным профилем, мусорный `X-Profile-Id` не роняет запрос).

### Слайс 5 — `client_trainer_edges`: миграция ключа `telegram_id` → `client_id`
**Статус:** DONE

Миграция `0190_client_edges_client_id`: nullable `client_id` (FK `clients.id`, `ON DELETE CASCADE`), бэкофилл из `clients.telegram_id`, уникальный индекс `(telegram_id, trainer_id)` заменён на `(client_id, trainer_id)` — это и есть настоящий фикс: раньше один и тот же аккаунт физически не мог иметь два разных «мой тренер» для разных профилей, теперь может. `telegram_id` остаётся `NOT NULL` — нужен для адресации пуш-уведомлений (у гостевого профиля-ребёнка своего Telegram-чата нет) и для заполнения новых строк.

`client_trainer_edge_repository.py` и `client_trainer_edge_use_cases.py` переведены на `client_id` как основной ключ (`telegram_id` передаётся отдельным параметром только туда, где нужен — INSERT новой строки и синк legacy `client_sessions.selected_trainer_id`). `client_trainer_primary_graph.py` не тронут — чистые функции без обращения к БД, ключ им не важен.

Также обновлены зависимые точки, которые эпик не называл явно, но которые ломались или оставались бы «дырявыми» без этого:
* `webapp_client_trainer_edges.py` — весь роутер (`save`/`unsave`/`primary`/`notify-slots`/`trainer-edges`/`catalog-trainer`) получил `X-Profile-Id`. Запись эджа без `clients`-строки (ещё не зарегистрирован) теперь явный `400 "Сначала завершите регистрацию"`, а не тихая orphan-строка, которую `WHERE client_id = NULL` никогда бы не нашёл обратно.
* **Найден и исправлен баг** в `client_pass_order_use_cases.py`/`client_cert_order_use_cases.py`: `submit_pass_product_order_request`/`submit_certificate_product_order_request` уже принимали `client_id` (после Слайса 4), но сверяли его с `get_client_id_by_telegram_id` (только self-профиль) — заявка на абонемент/сертификат от лица профиля-ребёнка всегда падала с `client_mismatch`. Исправлено на `resolve_acting_client_id`; заодно раздельные duplicate/daily-limit проверки теперь тоже per-profile, а не per-account.
* `GET /client/pass-order/catalog`, `GET /client/cert-order/catalog` — тоже получили `X-Profile-Id` (были готовы под это, просто не подключены).
* `_hub_session` внутри `GET /client/hub/bootstrap` — `edges`/`explicit_primary` теперь по профилю; booking-history-часть (`_bookings`, `_requests`, «последняя/предстоящая запись») остаётся на аккаунте — она в других модулях, вне периметра Слайса 5.
* `purge_past_booking_from_schedule_history` (booking_use_cases.py) — упрощён: раньше пересчитывал edge-статистику через `JOIN clients ON c.telegram_id = ...`, теперь просто по уже доступному `booking.client_id`.
* Инвайт-флоу (`client_invite_use_cases.py::bind_client_invite_trainer_context`) — уже резолвил `client_id`, просто не передавал его в `set_primary_trainer`.

Тесты: `tests/api/test_client_trainer_edges_slice5.py` (4 теста — save/primary/notify-slots изолированы по профилю, запись без регистрации — явный 400).

### Слайс 6 — UI: переключатель профиля + «Добавить ребёнка»
**Статус:** DONE, проверено вживую в браузере

Новый самодостаточный модуль `static/webapp/client-profile-switcher.js` (vanilla JS, без сборки — как весь остальной `static/webapp/`), две задачи в одном файле:

1. **Глобальный патч `window.fetch`** — навешивает `X-Profile-Id` на любой запрос к `/api/webapp/client/*`, если выбран не дефолтный профиль (иначе заголовок вообще не отправляется — нулевое изменение поведения для аккаунтов, которые ни разу не тронули переключатель). Подключено на **всех** клиентских страницах (`catalog.html`, `book.html`, `client-bookings.html`, `client-requests.html`, `client-passes.html`, `client-certificates.html`, `client-passes-certificates.html`, `client-buy-pass.html`, `client-saved-trainers.html`, `client-family-access.html`, `client-stats.html`, `client-home.html`) — по одному тегу `<script>` на файл, без правки их собственных fetch-вызовов.
2. **Чип + bottom sheet + форма «Добавить ребёнка»** — рендерится только туда, где есть `#clientProfileSwitcherMount` (сейчас только `client-home.html`, в `.hub-hero`, верхний правый угол). Чип показывается даже при единственном (self) профиле — иначе для первого добавления ребёнка не было бы входной точки. Список берётся из `GET /client/profiles`; выбор профиля или добавление ребёнка (`POST /client/profiles` → `PATCH .../default`) пишет `localStorage` (`cw_active_profile_id_v1`) и делает `location.reload()` — самый простой способ гарантировать, что ни один блок на странице не останется с данными предыдущего профиля.

Визуально переиспользует существующие токены (`--tg-theme-*`, `--app-cta-*`) и паттерн оверлея из `mini-app-components.css`/`mini-app-confirm.js`, со своими `.cps-*` классами (bottom sheet, а не тот же top-modal, что у `showAppConfirm`).

**Проверено вживую** (общий Playwright MCP браузер был занят соседней сессией весь основной проход — вместо него поднят изолированный Chrome через `playwright-core` напрямую, отдельный `--user-data-dir`, не трогает общий профиль): реальная навигация на `client-home.html` с этого же сервера, замоканы только сетевые ответы `/api/webapp/client/*` (сама логика — не мок). Прогнан полный сценарий: чип рендерится → клик открывает шторку → пустое имя блокирует сабмит с ошибкой и без запроса → валидное имя шлёт `POST /client/profiles` с правильным телом → `PATCH .../default` → `localStorage` и `location.reload()` → после релоада чип показывает нового ребёнка → переключение обратно на себя корректно синхронизируется с `localStorage`.

Найдено и исправлено **вживую, не через ручной review** (то есть без реального браузера эти два бага остались бы в проде):
1. **Чип был нерабочим** — `#clientProfileSwitcherMount` не имел `z-index`, соседний `#hubGreeting` (full-width `<div>` без фона, идёт следом в DOM) перехватывал клики поверх чипа. Визуально всё выглядело нормально, но тапнуть было невозможно. Это и есть причина, по которой чип не появлялся/не работал у пользователя при первой проверке. Фикс: `z-index:2` на mount-контейнер.
2. В шторке имя и роль профиля («Максим» / «Вы») схлопывались в одну строку («МаксимВы») — `.cps-row__name`/`.cps-row__role` были `<span>` без `display:block`. Добавлен `display:block` на оба класса.

---

## Прогресс

| Слайс | Статус |
|---|---|
| 1. Схема + бэкофилл | ✅ DONE |
| 2. Use-cases | ✅ DONE |
| 3. Endpoints профилей | ✅ DONE |
| 4. Переключение существующих эндпоинтов | ✅ DONE (суженный периметр, см. слайс) |
| 5. Миграция `client_trainer_edges` | ✅ DONE |
| 6. UI переключателя | ✅ DONE, проверено вживую в браузере |
