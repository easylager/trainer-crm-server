---
task_id: TASK-046
title: Тренер сам добавляет недостающую арену через простую форму
status: READY
phase: implement
execution_mode: AUTONOMOUS
created_at: 2026-09-04
updated_at: 2026-09-04
---

# Task

## Objective

Дать тренеру возможность самостоятельно и быстро добавить недостающую арену/каток через простую форму — не дожидаясь администратора — независимо от того, есть ли в его городе уже другие арены. Модерация происходит постфактум и не блокирует работу тренера.

## Business Context

Это E0.2 из `.ai/PLAN-CLIENT-GROWTH-2026.md` — Gate 0 для запуска платного трафика в Москву: «тренер из Москвы проходит регистрацию → добавляет арену → ставит слоты → его клиент записывается». Пока тренер не может завести свою арену полностью самостоятельно, платный трафик на Россию не запускать.

Конкретный триггер задачи — реальный баг, из-за которого тренер сегодня «заходит и не находит нужную арену»: в экране «Арены» профиля тренера (`static/webapp/trainer-profile-main.js`, `renderArenas()`) способ добавить недостающую площадку показывается только когда в городе вообще нет ни одной активной арены (`state.arenasList.length === 0`). Как только в городе есть хотя бы одна арена — а после запуска рекламы и роста количества городов это почти всегда так — чек-бокс список рисуется без единого способа добавить то, чего в нём нет.

## Scope

### In Scope

- Форма добавления арены (название, адрес; город берётся из профиля тренера, повторно не спрашивается) в экране «Арены» профиля тренера — доступна всегда, не только при пустом списке арен города.
- Та же точка входа в шаге онбординга «где вы тренируете» (частично уже существует как `arena_work_format=pending_request` — переиспользуется/переделывается, не дублируется отдельным вторым UI).
- Серверная часть: режим создания реальной арены на `POST /api/webapp/trainer/profile/arena-setup` (или соседний эндпоинт) — синхронный геокодинг адреса, мягкая проверка на дубль (радиус ~150 м по координатам + нормализованное название), запись новой строки в `arenas` со статусом «не подтверждена».
- Миграция: поля модерации на `arenas` (кто создал — привязка к тренеру, статус подтверждения, кто/когда подтвердил).
- Правило видимости новой арены: сразу видна создавшему тренеру и другим тренерам того же города (могут выбрать её для своего расписания); не показывается клиентам в публичном каталоге до подтверждения модератором.
- Очередь постфактум-модерации новых арен для администратора — переиспользуя существующий паттерн admin-бота (карточка + approve/reject), а не отдельный новый UI.
- Замена старого пути `arena_work_format=pending_request` (текстовое сообщение в поддержку, без реальной арены) на создание настоящей арены сразу.

### Out of Scope

- Формат «мобильный тренер» (`arena_work_format=mobile`, без привязки к арене) — не меняется, это отдельный легитимный случай.
- TASK-012 (сезонная арена), TASK-014 (несколько городов в онбординге) — соседние задачи, не расширяем эту задачу на них.
- Публичные индексируемые страницы арен, фотогалерея арены, внешние источники/парсинг данных (`PRODUCT-ARCHITECTURE-2026.md` §6.3/§9, Фаза 3 Foundation) — не в этой задаче.
- Инструмент слияния дублей у администратора — решение по дублю на этапе модерации ручное (текстом/кнопкой), отдельный merge-UI не строим.
- Выбор точки на карте при создании — форма текстовая (название + адрес), без карты.

## Acceptance Criteria

### AC-001
Тренер в экране «Арены» профиля видит способ добавить недостающую площадку независимо от того, есть ли уже арены в его городе — не только когда список пуст.
Requirement: CONFIRMED
Verification method: manual/exploratory (сценарий: город с 1+ активной ареной → в UI есть путь добавить ещё одну) + automated/unit (рендер компонента с непустым `arenasList`)

### AC-002
Форма добавления арены — минимум полей: название и адрес; город определяется из профиля тренера и повторно не запрашивается.
Requirement: CONFIRMED
Verification method: manual/exploratory (визуальная проверка формы) + automated/unit (валидация обязательных полей)

### AC-003
После отправки формы создаётся реальная запись в `arenas` (а не только текстовое сообщение в поддержку) — тренер может сразу выбрать эту арену и использовать её в расписании, не дожидаясь решения модератора.
Requirement: CONFIRMED
Verification method: automated/integration (POST создаёт строку в `arenas`, тренер может привязать к ней шаблон расписания сразу после ответа)

### AC-004
Новая арена сразу доступна для выбора создавшему тренеру и другим тренерам того же города; клиентам в публичном каталоге не показывается, пока модератор её не подтвердит.
Requirement: CONFIRMED
Verification method: automated/integration (два разных эндпоинта/предиката — список арен для тренера включает неподтверждённую, `/api/public/arenas`-путь клиентского каталога — нет)

### AC-005
Если адрес/координаты новой арены совпадают с уже существующей (радиус ~150 м) или название после нормализации похоже на существующее — тренер видит мягкое предупреждение с возможностью выбрать существующую арену или всё равно продолжить создание новой (не жёсткая блокировка).
Requirement: INFERRED (совпадение по радиусу и имени — из `PLAN-CLIENT-GROWTH-2026.md`; то, что предупреждение мягкое, а не блокирующее — вывод из общего принципа продукта «не спрашивать, пока не блокирует действие», не сказано этой фразой явно про этот конкретный случай)
Verification method: automated/unit (функция дубль-проверки: совпадение в радиусе/по имени → предупреждение; отсутствие совпадения → без предупреждения) + manual/exploratory (сценарий «продолжить всё равно»)

### AC-006
Старый путь `arena_work_format=pending_request` (создающий только текстовое сообщение в поддержку) заменяется этим механизмом и перестаёт существовать как отдельный способ добавления арены.
Requirement: CONFIRMED
Verification method: static analysis (в коде не остаётся вызовов старого пути / он ведёт на новый флоу) + manual (ручная проверка, что старый текст-запрос больше не создаётся)

### AC-007
При отклонении («reject») администратором арены на постфактум-проверке (мусор, дубль, неверные данные) арена деактивируется сразу (`is_active=false`) — даже если её уже выбрал(и) и использует(ют) в расписании один или несколько тренеров. Отзыв у тренеров происходит безусловно, не только пока арена «свободна».
Requirement: CONFIRMED
Verification method: automated/integration (reject → `is_active=false`, арена пропадает из выбора для новых слотов) + manual/exploratory (сценарий: два тренера уже используют арену → reject → оба теряют доступ; см. EDGE-003 про их уведомление)

## Edge Cases

### EDGE-001
Тренер создаёт арену, дублирующую уже существующую (проигнорировал мягкое предупреждение или совпадение не было найдено алгоритмом) — в городе со временем накапливаются дубли одной и той же площадки под разными названиями.
Severity: MEDIUM
Status: OPEN

### EDGE-002
Геокодинг не находит адрес или находит несколько совпадений (типично для катков без точного почтового адреса — только «ледовый дворец, за ТЦ»).
Severity: LOW
Status: OPEN

### EDGE-003
Арену создал тренер, чей аккаунт впоследствии деактивирован/заблокирован; к этому моменту арену уже мог выбрать и использовать другой тренер. Отдельно: по AC-007 отклонение арены при модерации деактивирует её безусловно — если её уже использует другой тренер, его слоты/шаблоны ссылаются на неактивную арену. Как именно он об этом узнаёт (уведомление, состояние UI в «Расписании») — не определено, решить в /plan.
Severity: MEDIUM
Status: OPEN

## Assumptions

- Геокодинг при создании арены не блокирует сохранение: если адрес не геокодируется однозначно, арена всё равно создаётся (без координат или с приблизительными), координаты донастраивает администратор при модерации. Основание — принцип продукта «не спрашивать, пока не блокирует действие с живым человеком» (`.ai/RESEARCH-onboarding-multi-arena.md`), явно не сформулировано именно для этого случая в `PLAN-CLIENT-GROWTH-2026.md`.
- Для геокодинга переиспользуется тот же провайдер, что и в `scripts/geocode_arena_addresses.py` (Nominatim/OSM), не заводится новый.
- Очередь постфактум-модерации новых арен переиспользует существующий паттерн admin-бота (`src/bot/admin_moderation_card.py`, `/pending`, `ADMIN_APPROVE_PREFIX`/`ADMIN_REJECT_PREFIX` в `src/bot/handlers/admin_handlers.py`) — по аналогии с модерацией профиля тренера (`profile_pending`/`photo_pending`), а не отдельный новый UI/флоу.
- Форма без поля «комментарий» (в отличие от старого `pending_request`, где было опциональное поле note) — минимальный набор полей ради простоты; при необходимости комментарий можно добавить в /plan, не меняя AC.
- Лимит на число неподтверждённых арен от одного тренера сознательно не вводится в этой задаче (решение пользователя) — риск спама/мусорных дублей принят как приемлемый на данном этапе; при необходимости лимит добавляется отдельной задачей, без пересмотра этой.

## Technical Plan

### Approach
Расширить существующий `POST /api/webapp/trainer/profile/arena-setup` новым режимом `mode=create`, который синхронно создаёт настоящую строку `arenas` с флагом `is_confirmed=false` и авто-привязывает её к тренеру-создателю. Развести видимость через два разных эндпоинта чтения (авторизованный — для тренеров, включает неподтверждённые; публичный — для клиентского каталога, только подтверждённые), а не через параметр на одном публичном роуте. На фронте убрать гейт «форма добавления арены видна только при пустом списке» и завести отдельную форму название+адрес вместо старой текстовой заявки в поддержку. Модерация — новая пара admin-bot команд/callback по образцу существующей модерации профиля тренера.

### Key finding, meняющий реализацию AC-004
`GET /api/public/arenas` (`src/api/routes/public.py:361`, `CatalogRepository.list_arenas`) сегодня — единственный источник арен и для тренерского экрана «Арены» (`trainer-profile-main.js:4993 loadArenasForCity`), и для клиентского каталога (`catalog-main.js:4032`). Эндпоинт без авторизации, различить «это тренер» и «это клиент» на нём нельзя. Поэтому AC-004 реализуется разведением на два пути чтения, а не фильтром-опцией на одном:
- Новый `GET /api/webapp/trainer/profile/arenas?city_id=` (авторизация как у остальных `/trainer/profile/*` — `get_trainer_miniapp_principal`) — `WHERE city_id=:cid AND is_active` (без фильтра по `is_confirmed`) — тренер видит все активные арены города, включая неподтверждённые.
- `GET /api/public/arenas` — добавить `AND is_confirmed` в SQL. Единственный другой потребитель (`catalog-main.js`) сразу получает нужное поведение без изменений на своей стороне.
- `trainer-profile-main.js:loadArenasForCity` переключить на новый эндпоинт.

### Changes

**Миграция `migrations/versions/0187_arena_trainer_created.py`:**
- `arenas.created_by_trainer_id INTEGER NULL REFERENCES trainers(id) ON DELETE SET NULL`
- `arenas.is_confirmed BOOLEAN NOT NULL DEFAULT true` — существующие/админские арены остаются подтверждёнными задним числом, только новые тренерские создаются с `false`
- `arenas.confirmed_at TIMESTAMPTZ NULL`, `arenas.confirmed_by_admin_id INTEGER NULL`
- Отклонение (AC-007) отдельного поля не требует — переиспользуется существующий `is_active`

**`src/infrastructure/db/models.py`** — 4 новых поля на `Arena` (AC-003, AC-004, AC-007).

**`src/infrastructure/repositories/catalog_repository.py`** — `list_arenas(..., include_unconfirmed: bool = False)`; `AND is_confirmed` в SQL, когда `False` (AC-004).

**`src/api/routes/public.py:361`** — `get_arenas` без изменений сигнатуры, `list_arenas(session, city_id, service_id=..., include_unconfirmed=False)` (AC-004).

**`src/api/routes/webapp_trainer_profile.py`**:
- Новый `GET /trainer/profile/arenas?city_id=` → `list_arenas(..., include_unconfirmed=True)`, ограничить `city_id` профилем тренера, если параметр не совпадает с ним (защита от чтения чужого города — не строгая, данные не приватные, но нет смысла звать с чужим id) (AC-004).
- `TrainerArenaSetupBody` — добавить `address: str | None`, `confirm_duplicate: bool = False`; режим `mode == "create"` (AC-002, AC-003, AC-005).
- Удалить ветку `mode == "request"` и вызов `submit_trainer_arena_request` (AC-006).

**Новый `src/application/trainer_arena_create_use_cases.py`** (или расширить `trainer_arena_setup_use_cases.py`):
- `find_possible_duplicate_arenas(session, city_id, name, lat, lon) -> list[dict]` — совпадение по нормализованному имени ИЛИ по радиусу ~150 м (если координаты есть). (AC-005)
- `create_trainer_arena(session, trainer_id, *, name, address, confirm_duplicate=False) -> dict` — резолвит `city_id` из профиля тренера; геокодирует адрес синхронно (переиспользовать провайдера из `scripts/geocode_arena_addresses.py`), не блокирует сохранение при неудаче геокодинга (Assumption, EDGE-002); при найденных дублях без `confirm_duplicate` — возвращает `{"duplicates": [...]}` без записи; иначе `INSERT INTO arenas (..., is_active=true, is_confirmed=false, created_by_trainer_id=trainer_id)` + `INSERT INTO trainer_arenas` (авто-привязка к создателю — иначе AC-003 «тренер может сразу выбрать» требует лишнего клика). (AC-002, AC-003, AC-005)
- Удалить/перестать вызывать `submit_trainer_arena_request` и `ARENA_WORK_FORMAT_PENDING_REQUEST`-ветку (AC-006); `set_trainer_arena_mobile` и `ARENA_WORK_FORMAT_MOBILE` не трогаются (out of scope).

**`static/webapp/trainer-profile-main.js`**:
- `loadArenasForCity` → новый авторизованный эндпоинт (см. Key finding). (AC-004)
- `renderArenas()` (`:4936`) — убрать `if (!state.arenasList.length) {...; return;}` как единственный путь к форме добавления; список чекбоксов и блок «добавить арену» рендерятся независимо друг от друга. (AC-001)
- `renderArenaEmptyActions` → переименовать по смыслу (например `renderArenaAddEntryPoint`), убрать гейт `(state.trainer.arena_ids||[]).length` — вход виден всегда, когда есть город. (AC-001)
- `renderArenaRequestForm` (`:4753`, name+note→support-заявка) заменить на `renderArenaCreateForm` (name+address→`mode:'create'`); обработать ответ с `duplicates` — мягкое предупреждение с выбором «использовать существующую» / «всё равно создать» (AC-005); по успеху — новая арена появляется в списке и отмечена выбранной, форма закрывается (`afterArenaSetupSuccess`). (AC-002, AC-003, AC-005)
- Небольшая пометка «на проверке» у неподтверждённых арен в списке чекбоксов — не отдельный AC, но нужна для «не двусмысленно»: тренер должен понимать, что новая арена ещё не прошла модерацию.
- `renderArenaSupportBlock` (общая заявка в поддержку) и `mode:'mobile'`-ветка не меняются (out of scope).

**Admin-бот** (по аналогии с `src/bot/admin_moderation_card.py` + `admin_handlers.py:121-306`, не переиспользуя те же функции — они специфичны для профиля тренера):
- Новая команда очереди (например `/pending_arenas`) — список арен `is_confirmed=false AND is_active=true`, карточка: название, адрес, город, тренер-создатель.
- `admin:arena:approve:{id}` → `is_confirmed=true, confirmed_at=now(), confirmed_by_admin_id=<admin>`.
- `admin:arena:reject:{id}` → `is_active=false`, безусловно (AC-007), независимо от того, использует ли её уже кто-то ещё.

### Data/API
```
POST /api/webapp/trainer/profile/arena-setup
  {"mode": "create", "arena_name": str, "address": str, "confirm_duplicate"?: bool}
  → 200 {"status": "duplicate_warning", "duplicates": [{"arena_id","name","address","distance_m"}]}
  → 200 {"status": "created", "trainer": {...}, "moderation_readiness": {...}}

GET /api/webapp/trainer/profile/arenas?city_id=  (новый, авторизованный)
  → {"items": [...]}  // включает is_confirmed=false

GET /api/public/arenas?city_id=  (существующий, публичный)
  → {"items": [...]}  // только is_confirmed=true
```

### Tests
- unit: `find_possible_duplicate_arenas` — радиус, нормализованное имя, отсутствие совпадений (AC-005)
- integration: `mode=create` → строка в `arenas` (`is_confirmed=false`, `created_by_trainer_id`), авто-привязка в `trainer_arenas` (AC-002, AC-003)
- integration: дубль без `confirm_duplicate` → не создаёт запись, возвращает `duplicates`; повтор с `confirm_duplicate=true` → создаёт (AC-005)
- integration: новая арена видна в `GET /trainer/profile/arenas`, отсутствует в `GET /api/public/arenas` (AC-004)
- integration: admin approve → `is_confirmed=true`; admin reject → `is_active=false` и арена пропадает из обоих списков, даже если уже выбрана другим тренером (AC-007)
- unit/frontend: `renderArenas()` показывает вход в форму добавления и при непустом `arenasList`, и когда `arena_ids` уже не пуст (регрессия на баг из AC-001)
- static: не осталось вызовов `submit_trainer_arena_request` / `mode === 'request'` (AC-006)

### Risks
- **EDGE-003 не закрыт полностью**: AC-007 определяет само отключение (`is_active=false`), но не уведомление тренеров, чьи слоты на этой арене сломались при reject — в этом плане не реализуется, оставлено как нерешённый остаток задачи (см. TASK-046 EDGE-003); если это должно блокировать релиз — нужно отдельное решение, не подразумевать по умолчанию.
- Синхронный геокодинг на request может быть медленным/ненадёжным (внешний сервис) — не должен блокировать создание арены (Assumption), но стоит проверить таймаут на проде.
- В репозитории параллельно работает несколько Claude-сессий над этим же деревом (см. память `feedback-parallel-sessions-git-safety`) — перед началом правок `trainer-profile-main.js` и `webapp_trainer_profile.py` стоит проверить `git status`/`ListAgents`, чтобы не столкнуться с чужими незакоммиченными изменениями в тех же файлах.
- Исторические тренеры в `arena_work_format=pending_request` не мигрируются — их старые заявки остаются как есть, только путь для новых заявок меняется (согласуется с AC-006, но явного backfill нет).

## Open Questions

Открытых вопросов не осталось — обе развилки (поведение при reject, анти-спам лимит) закрыты решением пользователя, см. AC-007 и Assumptions.

## Execution History

- **TASK_CREATED** — заведена по итогам разговора о самостоятельном добавлении арены тренером; источник требований — `PLAN-CLIENT-GROWTH-2026.md` §E0.2 (Gate 0 для запуска Москвы)
- **PHASE_STARTED** | clarify
- **CORRECTION** — черновик AC-001..AC-006 и Execution History изначально были сгенерированы фоновым research-агентом, вышедшим за рамки мандата «только собери факты»; при этом запись «решение подтверждено через AskUserQuestion в этом же разговоре» была недостоверной — такого вызова не было. Формулировки AC-001..AC-006 по фактам кода сохранены как рабочий черновик, но статус подтверждения ниже отражает реальный, отдельно проведённый диалог с пользователем
- **PHASE_COMPLETED** | clarify — видимость новой арены (AC-004: тренерам города сразу, клиентам каталога только после подтверждения) и поведение при reject (AC-007: деактивация сразу, даже если арена уже используется) подтверждены пользователем через AskUserQuestion в этом разговоре; анти-спам лимит сознательно не вводится (Q-002 закрыт как «не делать сейчас»). Итог: 7 AC (6 CONFIRMED, 1 INFERRED — AC-005), 3 edge cases, открытых вопросов не осталось
- **PHASE_STARTED** | plan
- **PHASE_COMPLETED** | plan — исследован код (`trainer_arena_setup_use_cases.py`, `webapp_trainer_profile.py`, `trainer-profile-main.js:renderArenas/loadArenasForCity`, `public.py:get_arenas`, `catalog_repository.py:list_arenas`, `admin_moderation_card.py`/`admin_handlers.py:121-306`). Ключевая находка: `/api/public/arenas` сегодня один и тот же неавторизованный источник и для тренерского экрана, и для клиентского каталога — AC-004 реализуется разведением на два эндпоинта чтения (новый авторизованный `GET /trainer/profile/arenas` для тренеров + фильтр `is_confirmed` на публичном), не параметром на одном роуте. Онбординг отдельного UI не требует — использует тот же экран профиля (в коде онбординга своей арена-формы не нашлось). EDGE-003 (уведомление тренеров при reject) в плане не закрыт — явно оставлен риском, не решён по умолчанию.
- **PHASE_STARTED** | implement — автономный режим, без human gates (по прямому запросу пользователя в разговоре)
- **PHASE_COMPLETED** | implement — реализовано и самостоятельно протестировано:
  - Миграция `migrations/versions/0187_arena_trainer_created.py` (применена к dev и test БД): `arenas.created_by_trainer_id`, `is_confirmed` (default true — задним числом подтверждает существующие/админские арены), `confirmed_at`, `confirmed_by_admin_id`. `Arena` в `models.py` обновлена.
  - `src/application/trainer_arena_create_use_cases.py` (новый) — `find_possible_duplicate_arenas` (радиус ~150м + нормализованное имя) и `create_trainer_arena` (геокодинг синхронный best-effort через Nominatim, никогда не блокирует создание; авто-привязка к создателю).
  - `src/application/trainer_arena_setup_use_cases.py` — `submit_trainer_arena_request` удалена (AC-006); константа/TTV-гейт для legacy `pending_request` оставлены для уже существующих тренеров.
  - `webapp_trainer_profile.py` — `POST /trainer/profile/arena-setup` получил `mode=create` (`mode=request` убран, теперь 422), новый `GET /trainer/profile/arenas` (авторизованный, включает неподтверждённые арены города).
  - `catalog_repository.py`/`catalog_use_cases.py` — `list_arenas(..., include_unconfirmed=False)`; `/api/public/arenas` фильтрует `is_confirmed` (клиентский каталог не видит неподтверждённые).
  - `src/application/admin_arena_moderation.py` (новый) + `admin_handlers.py` — команда `/pending_arenas`, колбэки `admin:arena:approve:`/`admin:arena:reject:`; reject — безусловный `is_active=false` (AC-007).
  - Фронтенд `trainer-profile-main.js` — `renderArenas()` больше не прячет форму добавления при непустом списке (AC-001); `loadArenasForCity` переключён на новый авторизованный эндпоинт; `renderArenaCreateForm` (название+адрес) заменила `renderArenaRequestForm`; обработка `duplicate_warning` с выбором существующей арены или принудительным созданием (AC-005); бейдж «на проверке» у неподтверждённых арен в списке. `mini-app-trainer-profile.css` — стиль бейджа.
  - Тесты (все новые и связанные существующие — зелёные): `tests/application/test_trainer_arena_create.py` (5), `tests/application/test_admin_arena_moderation.py` (3), `tests/application/test_trainer_arena_setup.py` (2, обновлён), `tests/api/test_webapp_trainer_profile.py` (+3 новых сценария создания/дубля/удалённого `mode=request`). Полный прогон `tests/` — см. следующую запись.
