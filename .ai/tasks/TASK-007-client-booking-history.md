---
task_id: TASK-007
title: История записей в клиентском боте
status: COMPLETE
phase: review
created_at: 2026-08-31
updated_at: 2026-09-03
---

> ⚠️ Коллизия номера: не путать с `TASK-007.md` (онбординг тренера, COMPLETE) —
> два разных таска с одним номером, см. предупреждение в `.ai/TASKS.md` про
> аналогичную коллизию TASK-011. Не трогать `TASK-007.md`.

# Task

## Objective

Добавить в клиентском боте историю записей — список прошедших и будущих записей к тренеру.

## Business Context

- Клиент не может посмотреть свою историю записей
- Нет способа найти информацию о прошлой записи

## Scope

### In Scope

- Вкладка/переключатель «История» внутри существующего `client-bookings.html` (не отдельная страница)
- Прошедшие записи (сортировка по дате, новые в начале), с пагинацией/подгрузкой
- Будущие записи отдельным списком (существующий раздел, без регрессии)
- Переход по клику на запись к деталям
- Пустой экран для «Истории» без записей — осмысленно оформленный
- Переключатель между тренерами (чипы) в обоих разделах — «Предстоящие» и «История» — если у клиента записи больше чем с одним тренером
- Все терминальные статусы (включая отменённые/неявки) видны в истории — записи не должны «теряться»

### Out of Scope

- Изменение существующего экрана «Мои записи» сверх добавления вкладки-переключателя и чипов тренеров
- Non-HTTPS текстовый fallback в классическом aiogram-боте — функция только для Mini App

## Comprehension Tips

### Facts

- Клиентский бот (`src/bot/client_app.py`) — hub-only UX: команды бота очищены (`set_my_commands([])`), кнопка меню открывает Mini App `/webapp/client-home`. Экраны живут в FastAPI + static webapp, не в классических aiogram-клавиатурах.
- Upcoming-бронирования уже реализованы, но **только будущие**: `list_bookings_for_client()` (`src/application/booking_use_cases.py:3569`) фильтрует `s.status IN ('available','booked')`, `b.status IN ('pending','confirmed')`, `slot_end > CURRENT_TIMESTAMP`, сортировка по возрастанию.
- API: `GET /client/bookings` (`src/api/routes/webapp.py:2267`) → `client_bookings_days_payload()` (`src/api/routes/webapp_client_payloads.py:114`) группирует по дню.
- UI: `static/webapp/client-bookings.html` (список + `screenDetail` для тапа по записи, deep-link `?open_booking=<id>`, скелетон-загрузка, дневная группировка) — готовый паттерн UX для переиспользования под историю.
- Модель `Booking` (`src/infrastructure/db/models.py:697-746`): дата/время берутся из связанного `Slot`, нет отдельной колонки даты. `status`: `pending|confirmed|completed|cancelled|declined|no_show|payment_dispute|trainer_removed`. Есть `is_sandbox` — sandbox-записи исключаются из реальных списков в других use-case.
- В `src/application/` нет ни одного use-case для истории (только upcoming) — фича строится с нуля: новый use-case + новый/расширенный роут + новый UI-раздел.
- Bot framework: aiogram ≥3.2.0. Явной пагинации callback-кнопками в клиентском боте нет; ближайший паттерн пагинации — сырой SQL `LIMIT/OFFSET` в админ-коде (`booking_problem_admin_use_cases.py:57`).
- Не проверено (требует отдельного взгляда, не блокирует clarify): есть ли у тренера в `client_dossier_use_cases.py` / `trainer-bookings.html` аналогичный список прошедших сессий клиента, который стоило бы зеркалить по логике запроса.
- Идентичность клиента — единая и глобальная: `Client.telegram_id` уникален без привязки к тренеру (`src/infrastructure/db/models.py:432-455`); связь клиент↔тренер живёт отдельно в `client_trainer_edges` (`models.py:336-376`, уникальность `(telegram_id, trainer_id)`, есть `is_saved`/`is_primary`/`completed_count`/`last_booking_at`). `list_bookings_for_client` резолвит один `client_id` по `telegram_id` (`client_use_cases.py:670-690`) и возвращает записи **по всем тренерам сразу** — `trainer_id` есть в каждой строке брони. Значит переключатель тренеров в UI — это фильтр по уже присутствующим данным (группировка по `booking.trainer_id`, список тренеров для чипов — из `client_trainer_edges`), а не смена идентичности/сессии.
- Сессия клиента в Mini App (`get_client_miniapp_principal`, `src/api/miniapp_auth/deps.py:114-132`) несёт только `telegram_id` — никакого `trainer_id` в принципале нет, что подтверждает: один клиент = одна сессия на всех тренеров.

## Acceptance Criteria

- **AC-001** — Внутри существующего `client-bookings.html` появляется переключатель «Предстоящие / История» — записи прошлого показываются отдельно от будущих, в том же разделе, без отдельной страницы. Функция доступна только в Mini App (без fallback в классическом aiogram-боте).
  Status: CONFIRMED (Q-001, Q-004)
  Verification: manual / exploratory (Mini App, Telegram или dev-заглушка initData)

- **AC-002** — Прошедшие записи в «Истории» отсортированы по дате по убыванию (самая новая сверху).
  Status: CONFIRMED
  Verification: automated / integration (payload use-case)

- **AC-003** — Тап по записи в «Истории» открывает экран деталей, как и в текущем списке предстоящих записей (переиспользуется существующий `screenDetail`).
  Status: CONFIRMED
  Verification: manual / exploratory

- **AC-004** — История = дополнение к upcoming, а не только «слот в прошлом»: `status NOT IN ('pending','confirmed') OR slot_end <= now`. Это осознанное уточнение при планировании: буквальное «slot_end < now» создавало дыру — отменённая запись на **будущую** дату не попадала бы ни в upcoming (статус не pending/confirmed), ни в историю (слот ещё не прошёл), то есть пропадала бы из обоих списков. Партиционирование по дополнению upcoming исключает эту дыру и прямо реализует принцип пользователя «записи не должны теряться». В историю попадают **все** терминальные статусы (`completed`, `cancelled`, `declined`, `no_show`, `payment_dispute`, `trainer_removed`) с видимым статус-бейджем на каждой записи; `is_sandbox = true` исключены. Best practice подтверждает: Calendly/Fresha/Booksy не прячут отменённые/неявки из истории, а помечают статусом.
  Status: CONFIRMED (Q-002; предикат уточнён на /plan)
  Verification: automated / unit + integration (включая тест на партиционирование: объединение upcoming ∪ history = все записи клиента без пропусков и дублей)

- **AC-005** — Бэкенд отдаёт историю через новый use-case (`list_booking_history_for_client` или аналог, по образцу `list_bookings_for_client`) + новый/расширенный роут (`GET /client/bookings/history` либо `GET /client/bookings?scope=history`), с постраничной подгрузкой (курсор или `LIMIT/OFFSET`, размер страницы ~20-30) — не единоразовый жёсткий лимит.
  Status: CONFIRMED (Q-001, Q-003)
  Verification: automated / integration

- **AC-006** — Существующий функционал «Мои записи» (предстоящие) не регрессирует: поведение и данные для будущих записей не меняются.
  Status: CONFIRMED
  Verification: automated / integration (regression)

- **AC-007** — Пустое состояние «Истории» (нет ни одной прошедшей записи) оформлено осмысленно — понятный текст/иллюстрация, а не пустая белая область или экран как при ошибке загрузки.
  Status: CONFIRMED
  Verification: manual / exploratory

- **AC-008** — Если у клиента есть записи (текущие и/или прошедшие) больше чем с одним тренером, в обоих разделах («Предстоящие» и «История») появляется переключатель-чипы по тренерам; чип «Все» показывает записи по всем тренерам объединённо, конкретный чип — только по выбранному. При одном тренере чипы не показываются. Ни один тренер/запись не выпадает из списка независимо от выбранного чипа — переключение только фильтрует отображение, не данные на бэкенде. Уточнение на /plan: источник списка тренеров для чипов — различные `trainer_id` из фактических записей клиента (`bookings`), а не `client_trainer_edges` — в edges могут быть «сохранённые» тренеры без единой брони, что дало бы чип без записей за ним.
  Status: CONFIRMED
  Verification: manual / exploratory + automated / integration (payload с несколькими trainer_id)

- **AC-009** — Если тренер, у которого была запись, впоследствии удалён/деактивирован, запись остаётся видимой в истории клиента (не исчезает, не превращается в ошибку).
  Status: CONFIRMED
  Verification: automated / integration

## Edge Cases

- У клиента нет ни одной прошедшей записи — AC-007
- Клиент занимался у нескольких тренеров — AC-008 (чипы), записи по всем тренерам всегда доступны, ничего не теряется
- Тренер деактивирован после записи — AC-009, запись остаётся в истории
- Отменённая запись на будущую дату — не должна пропасть из обоих списков (закрыто уточнением AC-004)
- Глубокая ссылка `?open_booking=<id>` на запись из истории за пределами первой страницы пагинации — см. Risks

## Technical Plan

### Approach

Backend: новый use-case-партнёр к `list_bookings_for_client` — `list_booking_history_for_client` с тем же набором JOIN'ов, но предикатом-дополнением к upcoming (`status NOT IN ('pending','confirmed') OR slot_end <= now`), сортировкой по убыванию и постраничной выдачей (`OFFSET/LIMIT`, как в существующем админ-коде); плюс лёгкий запрос списка тренеров клиента для чипов. Новый роут `GET /client/bookings/history`. Frontend: в существующем `client-bookings.html` добавляется переключатель режима «Предстоящие/История» и (при >1 тренере) чипы тренеров, обе списочные и детальная вёрстки переиспользуются, с расширением статус-бейджей и скрытием кнопки отмены для завершённых/отменённых записей.

### Changes

1. **`src/application/booking_use_cases.py`** — новая функция `list_booking_history_for_client(session, client_telegram_id, *, offset=0, limit=20, trainer_id=None)`, копия структуры `list_bookings_for_client` (`:3569`) с изменённым `WHERE`/`ORDER BY`/пагинацией; переиспользует `_SQL_SLOT_END_TS`, `SQL_BOOKING_RESOLVED_ARENA_ID`. Возвращает также флаг «есть ли ещё» (запрос `limit+1` строк, отсечь последнюю). (AC-002, AC-004, AC-005)
2. **`src/application/booking_use_cases.py`** — новая функция `list_client_booking_trainer_options(session, client_telegram_id)`: `SELECT DISTINCT b.trainer_id, <trainer_name>` по ВСЕМ броням клиента (без фильтра upcoming/history, `is_sandbox=false`), для чипов. (AC-008)
3. **`src/api/routes/webapp_client_payloads.py`** — `client_booking_history_days_payload(session, telegram_id, offset, limit, trainer_id)`: группировка по дню как в `client_bookings_days_payload` (`:114`), плюс `has_more`; `client_booking_trainer_options_payload(...)` — плоский список `{trainer_id, trainer_name}` для чипов, используется на обоих экранах.
4. **`src/api/routes/webapp.py`** — новый роут `GET /client/bookings/history` (query: `offset`, `limit`, `trainer_id`), тот же auth-паттерн (`get_client_miniapp_principal` + `client_catalog_telegram_key`), рядом с существующим `GET /client/bookings` (`:2267`). Существующий роут `/client/bookings` дополнительно отдаёт `trainer_options` в теле ответа (одно небольшое доп. поле, без нового round-trip на старте экрана).
5. **`static/webapp/client-bookings.html`** — разметка: переключатель режима над `#listContent` (два таба «Предстоящие»/«История»), ряд чипов тренеров под ним (скрыт при ≤1 тренере). JS: `state.mode`, `state.historyDays`, `state.historyOffset`, `state.historyHasMore`, `state.trainerFilter`, `state.trainerOptions`; `loadHistory(reset)` по образцу `loadBookings()` (`:754`) с добавлением кнопки «Показать ещё»; `bookingCardHtml` получает флаг `isHistory` (нет кнопки отмены, статус-бейдж вместо pending/confirmed-текста); `findBookingById` (`:507`) ищет и в `state.days`, и в `state.historyDays`; `openBookingDetail` (`:540`) скрывает `detailCancelBtn`/`detailPolicyHint` и расширяет маппинг `detailStatus` на все статусы для исторических записей. Пустое состояние истории — через существующий `window.ClientShell.renderEmptyState` (`:723`), отдельный текст/иконка. Bump `?v=` во всех подключениях этого файла и связанных ассетов (см. Risks — установленная в проекте конвенция кэш-бастинга).
6. **`static/webapp/mini-app-client-bookings.css`** — модификаторы бейджа `.badge.completed/.cancelled/.declined/.no_show/.payment_dispute/.trainer_removed`; стили переключателя режима (`.cb-mode-tabs`/`.cb-mode-tab`); стиль кнопки «Показать ещё». Чипы тренеров переиспользуют существующие `.filter-chips`/`.filter-chip` из `mini-app-components.css` (уже подключён в этом файле, `:12`) — новых стилей для них не требуется.

### Data/API

- Новый эндпоинт: `GET /api/webapp/client/bookings/history?offset=&limit=&trainer_id=` → `{ days: [...], has_more: bool }`, формат дня идентичен существующему `/client/bookings` (`serialize_client_booking` переиспользуется без изменений).
- Существующий `GET /client/bookings` дополняет тело ответом полем `trainer_options: [{trainer_id, trainer_name}]` — обратной совместимости не нарушает (аддитивное поле).
- Партиционирование данных: `upcoming` (существующий предикат, не менян) ∪ `history` (новый предикат-дополнение) = все брони клиента без пропусков и пересечений — ключевое инвариант, проверяется тестом.

### Tests

- `list_booking_history_for_client`: возвращает completed/cancelled/declined/no_show/payment_dispute/trainer_removed; исключает pending/confirmed-с-будущим-слотом; исключает `is_sandbox`; сортировка DESC; пагинация `offset/limit` + `has_more`. (AC-002, AC-004, AC-005)
- Партиционирование: для фикстуры со смешанными статусами и датами `set(upcoming) ∪ set(history) == set(все брони клиента)` и пересечение пусто — ловит именно ту дыру с отменённой будущей записью, которая была уточнена в AC-004. (AC-004)
- `list_client_booking_trainer_options`: 1 тренер → список из 1; 2+ тренера → все перечислены; `is_sandbox` брони не создают лишний чип. (AC-008)
- Регрессия: `list_bookings_for_client` (upcoming) — те же результаты, что и до изменений, на одинаковой фикстуре. (AC-006)
- Деактивированный (не удалённый) тренер — его старые брони всё ещё возвращаются `list_booking_history_for_client` с корректным именем/полями. (AC-009)
- Роут `GET /client/bookings/history` — auth (401 без initData), happy path, `trainer_id` фильтр сужает выдачу. (AC-005, AC-008)
- Frontend (JS-раннера в проекте нет — установленный факт, см. `TASK-007.md` verification history): переключатель режима, чипы, пустой экран, бейджи и скрытие кнопки отмены проверяются `node --check` (синтаксис) + manual/exploratory в Mini App. (AC-001, AC-003, AC-007, AC-008)

### Risks

- **Уточнение предиката AC-004** — сознательное расхождение с буквальной формулировкой «slot_end < now» ради устранения дыры (см. Edge Cases); зафиксировано в самом AC-004.
- **Нет JS-раннера в проекте** — фронтенд-критерии верифицируются вручную/статически, как и в предыдущей одноимённой по номеру задаче (см. `TASK-007.md` verification history) — не новый прецедент, а уже принятая в проекте практика.
- **Глубокая ссылка на историческую запись за пределами первой страницы** — `?open_booking=<id>` сейчас ищет только в уже загруженных данных; если запись в истории далеко за первой страницей пагинации, deep-link её не найдёт сразу. Принято как ограничение MVP (deep-link используется в первую очередь для предстоящих записей из хаба, не для истории) — не блокирует AC, но стоит держать в уме при ревью.
- **Кэш-бастинг** — обязательно бампнуть `?v=` версии на изменённых `client-bookings.html`/CSS, иначе Telegram WebView может отдать закэшированную версию (установленная в проекте конвенция, видна в предыдущих задачах).
- **Объём правок в `client-bookings.html`** (941 строка, весь JS инлайном, без сборщика) — правки точечные (новые функции + расширение существующих), но файл велик; регресс-риск для существующего flow отмены записи снижается тем, что `bookingCardHtml`/`openBookingDetail` расширяются флагом, а не переписываются.

**Ready to implement**

## Verification Results

Прогон 2026-09-03 против `trainer_crm_test` (head-ревизия `0185_hint_dismissals`, синхронизирована заранее пользователем/окружением; боевая `trainer_crm` не затрагивалась — `DATABASE_URL`/`DATABASE_URL_SYNC` подменялись только в окружении процесса pytest).

| AC | Итог | Чем подтверждён |
|----|------|-----------------|
| AC-001 | VERIFIED (static) | Разметка: `#cbModeTabs` с двумя табами внутри `#screenList`, до `#listContent`; `switchMode()` переключает активный таб и рендер. Только Mini App — новый роут висит на `get_client_miniapp_principal`, fallback в aiogram не добавлялся (см. `test_history_route_requires_auth`). |
| AC-002 | VERIFIED | `test_history_sorted_newest_first` — DESC по `slot_date`/`start_time`/`id` |
| AC-003 | VERIFIED (static) | `findBookingById` ищет в `state.historyDays`; `bookingCardHtml`/`openBookingDetail` используют общий `screenDetail` |
| AC-004 | VERIFIED | `test_history_includes_all_terminal_statuses_and_excludes_upcoming`, `test_cancelled_future_booking_shows_in_history_not_upcoming` (закрывает именно ту дыру, ради которой уточнялся предикат), `test_history_partition_covers_all_bookings_no_overlap` (8 статусов, upcoming ∩ history = ∅, upcoming ∪ history = все брони), `test_history_excludes_sandbox` |
| AC-005 | VERIFIED | `test_history_pagination_offset_and_has_more` (3 страницы, `has_more` корректен на границах); роут `GET /client/bookings/history` — `test_history_route_happy_path`, `test_history_route_trainer_id_filter_narrows_results` |
| AC-006 | VERIFIED | `tests/application/test_list_bookings_for_client.py` — 2/2 passed без изменений; полный regression-прогон ниже |
| AC-007 | VERIFIED (static) | `renderHistoryList()` вызывает `window.ClientShell.renderEmptyState` с отдельными title/hint для «нет истории вообще» и «нет записей у выбранного тренера» |
| AC-008 | VERIFIED | Бэкенд: `test_trainer_options_lists_distinct_trainers_excludes_sandbox`, `test_trainer_options_single_trainer`, `test_history_trainer_id_filter`, `test_upcoming_route_includes_trainer_options`. Фронт (static): `renderTrainerChips()` скрывает ряд при `<2` тренеров, использует существующий `.filter-chip` |
| AC-009 | VERIFIED | `test_history_survives_deactivated_trainer` — тренер переведён в `deactivated` (не удалён, FK `ON DELETE CASCADE` не срабатывает), запись остаётся с корректным именем |

**Регрессия не внесена.** `tests/application` + `tests/api`: 6 failed, 956 passed, 3 skipped. Все 6 падений — предсуществующие и не связаны с этой задачей: `test_trainer_profile_demotion.py`, `test_trainer_services_remove_guard.py` (×2), `test_public_catalog_scenarios.py` падают в изолированном прогоне без единого файла, тронутого этой задачей. Оставшиеся два (`test_client_hub_bootstrap_exposes_primary_history`, `test_client_hub_bootstrap_includes_passes`) падают из-за несвязанного бага в `client_trainer_edges` (каст `last_completed_at` из строки в timestamptz) и падают вместе даже при изолированном прогоне только своего файла — не задеты кодом, который меняла эта задача (не трогал `client_trainer_edges`, `client_trainer_primary_graph.py`).

**Чего проверка НЕ покрывает:** Mini App не открывался в браузере — стандартный playwright-профиль уже занят другим процессом (`Browser is already in use`), а прямой прогон в Telegram требует подписанного `initData`, которого нет вне реального Telegram-клиента (роут гейтится на `get_client_miniapp_principal`, dev-bypass в коде отсутствует). Пять из девяти критериев подтверждены чтением кода и сверкой айдишников/классов, а не наблюдением работающего интерфейса — тот же структурный блок, что и в предыдущем раунде этой же по номеру задачи (см. `TASK-007.md`). Нужен ручной прогон в Telegram: таб «История», чипы тренеров при 2+ тренерах, пустой экран, статус-бейджи на карточках.

## Execution History

- **TASK_CREATED** — исходная todo-заметка от 2026-08-31, переведена в Task Context 2026-09-03
- **PHASE_STARTED** | clarify — черновик Acceptance Contract
- **PHASE_COMPLETED** | clarify — 6 AC зафиксированы (2 CONFIRMED, 4 INFERRED), исследован код клиентского бота/Mini App/модели бронирований (см. Comprehension Tips)
- **HUMAN_GATE** | clarify — Q-001…Q-004 открыты (архитектура вкладки/страницы, состав статусов истории, пагинация, нужен ли non-HTTPS fallback); AC-001, AC-004, AC-005 остаются INFERRED до ответов
- **PHASE_STARTED** | clarify (раунд 2) — ответы пользователя на Q-001…Q-004 + расширение скоупа (пустой экран, чипы тренеров)
- **PHASE_COMPLETED** | clarify — все вопросы закрыты, 9 AC зафиксированы (все CONFIRMED). Дополнительное исследование: идентичность клиента глобальна (`clients.telegram_id` без `trainer_id`), связь с тренерами — `client_trainer_edges`; переключатель тренеров реализуем как фильтр по уже существующим данным, без изменения identity/сессии.
- **PHASE_STARTED** | plan — построение технического плана
- **PHASE_COMPLETED** | plan — 6 файлов/модулей, план по backend (2 новых use-case, новый роут, расширение payload-билдеров) и frontend (режим-переключатель, чипы, статус-бейджи, пустой экран). Уточнены AC-004 (предикат-дополнение вместо буквального slot_end<now — закрывает дыру с отменённой будущей записью) и AC-008 (источник чипов — bookings, не client_trainer_edges).
- **PHASE_STARTED** | implement — execution_mode не задан, по умолчанию AUTONOMOUS; шесть срезов плана
- Срезы 1-4 (backend: `list_booking_history_for_client`, `list_client_booking_trainer_options`, payload-билдеры, роут `GET /client/bookings/history` + `trainer_options` в `/client/bookings`) и 5-6 (frontend: режим-переключатель, чипы, статус-бейджи, пустой экран, пагинация «Показать ещё», `?v=` → `202609030`) реализованы. По ходу исправлен баг в существующем `apiUrl()` (`client-bookings.html`) — не умел добавлять `init_data` к пути с query-параметрами; нужен для `offset/limit/trainer_id`, фикс приводит его к паттерну, уже используемому в `client-home-main.js`. `py_compile` + `node --check` чисты, баланс div-тегов в разметке сошёлся.
- **PHASE_COMPLETED** | implement
- **PHASE_STARTED** | verify — 14 новых тестов (10 unit/integration на use-case, 4 на роуты), полный `tests/application` + `tests/api`
- **PHASE_COMPLETED** | verify — 9/9 AC VERIFIED (4 — automated, 5 — static/code review из-за структурного блока на живом прогоне Mini App). Регрессия исключена: 956 passed, 6 предсуществующих непричастных падения подтверждены изолированными прогонами. Живой прогон в Telegram не выполнен — тот же блок, что и в предыдущем раунде этой задачи; см. Verification Results.
- **REVIEW** — 1 Medium, 1 Low. Medium: «Показать ещё» в истории зависает молча (disabled, «Загрузка…» навсегда) при сетевой ошибке подгрузки — catch-ветка `loadHistory()` не восстанавливает кнопку, если `historyLoaded` уже `true`. Low: `list_bookings_for_client`/`list_booking_history_for_client` — почти дословное дублирование SELECT/JOIN/маппинга строк (~90 строк), кандидат на общий helper при следующей правке этого участка.
- **PHASE_STARTED** | implement — фикс Medium-находки ревью
- **PHASE_COMPLETED** | implement — `loadHistory()` catch-ветка (`client-bookings.html`) теперь различает первичную загрузку (`!historyLoaded` → сообщение об ошибке в списке, без изменений) и «Показать ещё» (`historyLoaded === true` → кнопка возвращается в исходное состояние + `showAppToast` с ошибкой вместо зависания). `?v=` → `202609031`. `node --check` чист, баланс div сошёлся.
- **PHASE_STARTED** | verify — повторный прогон 16 тестов задачи после фикса
- **PHASE_COMPLETED** | verify — 16/16 passed (`test_list_booking_history_for_client.py`, `test_webapp_client_booking_history_route.py`, `test_list_bookings_for_client.py`). Medium-находка закрыта, регрессии не внесены. Low-находка (дублирование SQL) оставлена как принятый долг по решению пользователя.
- **COMPLETE** — пользователь одобрил фикс. 9/9 AC VERIFIED, Medium-находка ревью закрыта, Low принята как долг. Открытый пункт: живой прогон в Telegram Mini App не выполнен (структурный блок окружения — см. Verification Results), рекомендуется перед реальным релизом.
