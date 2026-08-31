---
task_id: TASK-010
title: Арены — жёсткий тупик на последнем шаге обязательного визарда
status: BLOCKED
phase: verify
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Дать тренеру выход, когда его площадки нет в справочнике арен. Сейчас на шаге 4 из 4 обязательного минимума он видит «Нет арен для выбранного города.» и не может завершить онбординг вообще — ни предложить свою арену, ни указать выездной формат, ни написать в поддержку.

## Business Context

Арена входит в TTV-минимум, без неё не открывается расписание и не отправляется анкета. Справочник арен конечен и наверняка неполон. Каждый тренер с площадкой вне справочника теряется молча и навсегда — мы даже не узнаем, что он приходил.

## Scope

### In Scope

- Пустое состояние блока «Арены» в профиле (`static/webapp/trainer-profile-main.js`, `trainer-profile.html`)
- Механика «предложить арену» (заявка модератору) и/или формат без привязки к площадке
- Поведение TTV-гейта, когда арена в процессе согласования
- Кнопка в поддержку как минимальная страховка

### Out of Scope

- Админский справочник арен и его наполнение (`admin-dicts`), кроме приёма заявок
- Геокодирование адресов арен

## Comprehension Tips

### Facts

- `static/webapp/trainer-profile-main.js:4508-4524` — `renderArenas()`: при пустом `state.arenasList` показывает hint «Нет арен для выбранного города.» (или «Выберите город…»), очищает `primaryArenaWrap` и делает `return`. Никаких альтернативных действий в этой ветке нет.
- Список грузится из публичного справочника: `loadArenasForCity` → `GET /api/public/arenas?city_id=...` (`trainer-profile-main.js:4553-4562`). При ошибке — тоже пустой список, тот же тупик.
- Арена обязательна на всех трёх планках: `analyze_tt_minimal_profile_readiness` (5 критериев), `analyze_moderation_submission_readiness` (8), `analyze_moderation_profile_completeness` (11) — `src/application/trainer_profile_completeness.py`, ключ `arenas`, лейбл «хотя бы одна арена».
- Без арены `resolve_trainer_access_state` даёт `BLOCKED_PROFILE` (`src/application/trainer_access_state.py:56-70`) → закрыты расписание, заявки, записи.
- `arenas` — последний шаг визарда: `PROFILE_TT_MINIMAL_WIZARD_ORDER = ['anketa_main', 'phone', 'services', 'arenas']` (`trainer-profile-main.js:161`). Тренер доходит до конца и упирается.
- Механики «предложить арену» в коде нет: поиск по `arena_suggest`, `arena_request`, «Добавить арену», «предложить арену» ничего не находит ни в `src/`, ни в `static/webapp/`.
- Первичная арена задаёт сетку расписания (`static/webapp/trainer-profile.html:426-429` — «Сетку задаёт ваша основная арена»), поэтому «просто сделать поле необязательным» ломает соседнюю механику.

### Implications

- Нельзя решить простым снятием обязательности: от основной арены зависит сетка слотов. Нужен либо явный формат «без площадки / выезд» с дефолтной сеткой, либо заявка на новую арену с временным разрешением работать.
- Самый дешёвый первый шаг, снимающий потерю вслепую: в пустом состоянии — кнопка «Моей площадки нет в списке» с отправкой заявки/обращения в поддержку. Даже без автоматики это превращает молчаливый отвал в лид.
- Проверить масштаб по проду: сколько городов в справочнике имеют ноль арен.

## Acceptance Criteria

### AC-001
Пустое состояние блока «Арены» (нет арен для города или ошибка загрузки списка) показывает не тупиковый текст, а три опции: подать заявку на арену, указать мобильный/выездной формат, написать в поддержку.
Requirement: CONFIRMED
Verification method: manual / e2e (UI), уже реализовано — `renderArenaEmptyActions` (`static/webapp/trainer-profile-main.js:4790-4874`, контейнер `trainer-profile.html:240`)
Result: BLOCKED
Evidence: нет живой Telegram WebApp сессии тренера в этой среде (нет dev-обхода auth) — нужен ручной прогон в браузере/Telegram

### AC-002
Тренер может отправить заявку на арену (название + опциональный комментарий); заявка сохраняется на тренере (`arena_work_format='pending_request'`, `arena_request_text`, `arena_request_at`) и одновременно уходит в поддержку как сообщение с тегом «профиль тренера · заявка на арену».
Requirement: CONFIRMED
Verification method: automated / unit + integration — `src/application/trainer_arena_setup_use_cases.py:submit_trainer_arena_request`, API `POST /trainer/profile/arena-setup` (`mode=request`, `src/api/routes/webapp_trainer_profile.py`)
Result: VERIFIED
Evidence: `tests/application/test_trainer_arena_setup.py::test_submit_arena_request_creates_support_ticket` PASSED (use-case уровень — сохранение полей + создание support-тикета). HTTP-роут `POST /trainer/profile/arena-setup` отдельного интеграционного теста не имеет — код прочитан вручную, диспетчеризация `mode` тривиальна, но end-to-end не прогонялась.
Verified at: 1ae921e (dirty, uncommitted arena-setup changes), 2026-08-31

### AC-003
Тренер может выбрать мобильный/выездной формат без привязки к арене (`mode=mobile` → `arena_work_format='mobile'`); сетку расписания в этом случае настраивает вручную в «Настройках», и доступ к бронированиям не блокируется отсутствием арены (`resolve_trainer_access_state` → `BOOKING_READY`).
Requirement: CONFIRMED
Verification method: automated / unit — `tests/application/test_trainer_access_state.py::test_booking_ready_with_mobile_format_and_no_arenas`
Result: VERIFIED
Evidence: `tests/application/test_trainer_access_state.py::test_booking_ready_with_mobile_format_and_no_arenas` PASSED; `tests/application/test_trainer_arena_setup.py::test_set_trainer_arena_mobile_persists` PASSED (27 тестов в test_trainer_access_state.py+test_trainer_profile_completeness.py — все зелёные)
Verified at: 1ae921e (dirty, uncommitted), 2026-08-31

### AC-004
TTV-минимум (`analyze_tt_minimal_profile_readiness` / `tt_minimal_arenas_satisfied`) считает критерий «арена» выполненным при: реальных аренах, ИЛИ мобильном формате, ИЛИ заявке на рассмотрении с непустым текстом — обязательный визард проходится и анкета отправляется во всех трёх случаях.
Requirement: CONFIRMED
Verification method: automated / unit — `tests/application/test_trainer_profile_completeness.py::test_tt_minimal_complete_with_mobile_format_without_arenas`, `::test_tt_minimal_complete_with_pending_arena_request`
Result: VERIFIED
Evidence: оба теста PASSED; также `tests/application/test_trainer_arena_setup.py::test_tt_minimal_arenas_satisfied_matrix` PASSED (матрица: реальные арены / mobile / pending_request с текстом / pending_request без текста)
Verified at: 1ae921e (dirty, uncommitted), 2026-08-31

### AC-005
Полный профиль для модерации (`analyze_moderation_profile_completeness`, 11 критериев) по-прежнему требует реальную арену — мобильный формат и заявка не подменяют её на этом более строгом уровне.
Requirement: CONFIRMED
Verification method: automated / unit — `tests/application/test_trainer_profile_completeness.py::test_full_profile_still_requires_real_arena_not_mobile`
Result: VERIFIED
Evidence: `test_full_profile_still_requires_real_arena_not_mobile` PASSED
Verified at: 1ae921e (dirty, uncommitted), 2026-08-31

### AC-006
В пустом состоянии всегда доступна отдельная кнопка «Написать в поддержку» (текстовое поле + `POST /support`) как страховка независимо от выбора заявки или мобильного формата.
Requirement: CONFIRMED
Verification method: manual / e2e (UI) — `renderArenaSupportBlock`, `static/webapp/trainer-profile-main.js:4634-4661`
Result: BLOCKED
Evidence: та же причина, что и AC-001 — нет живой Telegram WebApp сессии в этой среде для ручного прогона

## Edge Cases

### EDGE-001
Тренер меняет город профиля после того, как отправил заявку на арену для старого города — `arena_work_format`/`arena_request_text` не привязаны к городу и не сбрасываются при смене города, поэтому TTV-гейт останется разблокирован заявкой, которая относится к другому городу.
Severity: MEDIUM
Status: OPEN

## Assumptions

- В рабочей копии уже присутствует полная нераскоммиченная реализация всего In Scope (миграция `0178_trainer_arena_setup.py`, модель, use-case модуль, API-роут, фронтенд, юнит-тесты) — см. `git diff --stat` (87 файлов) и untracked-миграцию. Похоже, задача уже выполнена в предыдущей сессии, но не закоммичена и не проведена через `/verify`.

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **PHASE_STARTED** — clarify, 2026-08-31
- **PHASE_COMPLETED** — clarify: AC-001..AC-006 определены как CONFIRMED на основе уже существующей (нераскоммиченной) реализации в рабочей копии; открытых блокирующих вопросов нет, 2026-08-31
- **PHASE_STARTED** — verify, 2026-08-31
- **VERIFY_RUN** — поднята тестовая БД `trainer_crm_test` (миграции уже на head: `0178_trainer_arena_setup`), прогнаны `tests/application/test_trainer_profile_completeness.py`, `test_trainer_access_state.py`, `test_trainer_arena_setup.py` — 30/30 PASSED. AC-002..AC-005 → VERIFIED. AC-001, AC-006 (UI) → BLOCKED: нет живой Telegram WebApp сессии в этой среде. 2026-08-31
