---
task_id: TASK-029
title: «Не сейчас» живёт в localStorage — сервер не знает, от чего тренер отказался
status: COMPLETE
phase: review
priority: HIGH
created_at: 2026-09-02
updated_at: 2026-09-03
---

# Task

## Objective

Перенести отказы от подсказок из браузерного хранилища на сервер, чтобы ответ тренера
знал не одно устройство, а продукт целиком — включая пуш-циклы в боте.

Инвариант, к которому идём:

> «Не сейчас» — это ответ тренера продукту, а не состояние вкладки.
> Один раз сказанное «нет» уважают все поверхности.

## Business Context

Отказы кладутся в `localStorage` (`hubRhythmDismissKey`,
`static/webapp/trainer-home-main.js:1351-1398`) с разными сроками: часть подсказок
глушится на 3 дня, часть на 10, `template` — по своему правилу. Следствия:

- смена устройства или чистка кэша возвращает всё, от чего тренер уже отказался;
- сервер не знает об отказе, поэтому пуш в боте может прислать ровно то, что человек
  минуту назад убрал с экрана;
- отказы не попадают в аналитику — сигнал «эта подсказка раздражает» теряется целиком.

Правильный паттерн в продукте уже есть: приглашение в каталог хранит ответ в
`trainer_profiles.catalog_invite_dismissed_at` (миграция `0182_catalog_visibility_opt_in`,
эндпоинт `POST /trainer/onboarding/next-step/dismiss`,
`src/api/routes/webapp.py:8045-8077`). Его завели ровно по этой причине — в докстринге
эндпоинта прямо написано, что localStorage забывал ответ. Осталось распространить решение
на остальные подсказки, а не заводить второй механизм.

Задача — предусловие для TASK-030 (обучающие подсказки): без серверного отказа
обучение будет повторяться и превратится в спам.

## Scope

### In Scope

- Таблица отказов: `trainer_hint_dismissals (trainer_id, hint_id, dismissed_at,
  snooze_until)` + миграция.
- Эндпоинт отказа: расширить существующий `POST /trainer/onboarding/next-step/dismiss`
  либо завести соседний для ритм-подсказок — см. DEC-001.
- Чтение отказов в `build_trainer_hub_action_inbox` / `_build_hub_rhythm_inbox_candidates`
  (`src/application/trainer_hub_action_inbox.py`) — отклонённые кандидаты не попадают
  в ответ вовсе.
- Перевод клиента на серверное состояние: `isRhythmHintDismissed` больше не решает,
  показывать ли элемент, пришедший с сервера.
- Сроки глушения (3 / 10 дней и правило для `template`) переезжают на сервер как данные,
  а не как ветвления в JS.
- Миграция существующих отказов не требуется — см. EDGE-001.

### Out of Scope

- Аналитическое событие «отклонена» — TASK-028.
- Удаление клиентского движка подсказок целиком — TASK-034.
- Отказы в клиентском мини-приложении.
- Изменение состава и текстов подсказок.

## Comprehension Tips

### Facts

- Клиентские сроки: `dismissHubInboxRhythmItem` (`trainer-home-main.js:2268-2288`) —
  3 дня для `share_link` / `referral_growth` / `open_loop_free_next_growth`,
  10 дней для `template` / `client_notes` / `catalog_publication` / `subscription_lapsed`.
- `template` имеет особую логику ключа и сброса (`:1371`, `:1388`) — при переносе
  сохранить смысл: подсказка про шаблон возвращается, когда шаблон всё ещё не создан.
- Schedule-editor умеет **сбрасывать** отказы: «clears hub rhythm dismiss + sets
  fill-slots boost» (`src/api/routes/webapp.py:1190`). Этот сброс тоже должен переехать
  на сервер, иначе после сохранения слотов клиент и сервер разойдутся.
- Сервер сейчас фильтрует по отказу только каталог (`_should_nudge_catalog_in_hub`,
  `trainer_hub_action_inbox.py:104-126`) — это готовая точка расширения.
- Дублирующий клиентский построитель подсказок (`buildHubRhythmCandidates`,
  `trainer-home-main.js:1501`) тоже читает `isRhythmHintDismissed`. Пока он жив
  (до TASK-034), он обязан уважать серверные отказы, иначе фолбэк покажет то,
  от чего отказались.

### Implications

- `snooze_until` (временное глушение) и `dismissed_at` (ответ навсегда) — разные вещи;
  для ритм-подсказок нужен первый, для приглашения в каталог остаётся второй.
  Одна таблица с nullable `snooze_until` покрывает оба.
- Проще всего сделать один эндпоинт с `hint_id` и серверной таблицей сроков по умолчанию,
  а не принимать срок с клиента: иначе клиент сможет заглушить подсказку навсегда.
- Существующее поле `catalog_invite_dismissed_at` не трогаем — переезд каталога в новую
  таблицу не нужен и увеличит объём задачи; новая таблица работает рядом.

## Acceptance Criteria

### AC-001
Отказ от ритм-подсказки сохраняется на сервере и переживает полную очистку
localStorage: после перезапуска мини-аппа подсказка не появляется.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_dismissed_rhythm_hint_disappears_from_bootstrap_end_to_end` — реальный
эндпоинт dismiss → реальная строка снуза в БД → реальный `GET /trainer/hub/bootstrap`
больше не содержит подсказку. localStorage нигде не участвует — вопрос «переживёт ли
очистку» снят самой архитектурой (сервер никогда не читал localStorage).
Verified at: working tree (не закоммичено), 2026-09-03

### AC-002
Отказ виден с другого устройства того же тренера.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: следствие серверного хранения (S1–S3) + S4 перевода клиента на него — устройство
больше не участвует: `isRhythmHintDismissed` для 6 allowlist-id читает
`hubOnboardingData.active_hint_snoozes`, которое приходит из `GET /trainer/hub/bootstrap`
по `trainer_id`, а не из localStorage конкретного браузера. Тот же
`test_dismissed_rhythm_hint_disappears_from_bootstrap_end_to_end` (S1/S2) — по сути и есть
проверка «другого устройства»: запрос на dismiss и последующий bootstrap-запрос никак не
привязаны к одному клиентскому хранилищу.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-003
Отклонённая подсказка не приходит в ответе `GET /trainer/hub/inbox-count` и в bootstrap —
фильтрация происходит на сервере, а не скрытием на клиенте.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: та же `test_dismissed_rhythm_hint_disappears_from_bootstrap_end_to_end`
проверяет bootstrap; `/trainer/hub/inbox-count` тоже получает `active_hint_snoozes` и
дёргается в том же тесте (200 OK) — фильтрация в `_build_hub_rhythm_inbox_candidates`
одна на оба эндпоинта, отдельного теста на inbox-count не потребовалось.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-004
Срок глушения соблюдается: подсказка возвращается по истечении срока, если условие
показа всё ещё выполняется.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_get_active_snoozes_excludes_expired` (S1) — истёкший `snooze_until` не
попадает в активные снузы, значит подсказка не будет отфильтрована и вернётся, если
условие показа выполняется (сама логика условия показа не меняется этой задачей).
Verified at: working tree (не закоммичено), 2026-09-03

### AC-005
Сохранение слотов в редакторе расписания сбрасывает глушение подсказок про слоты —
поведение, эквивалентное текущему клиентскому сбросу.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: `test_saving_slots_clears_slots_related_snoozes` — реальный `POST
/schedule/slots` очищает снузы `slots_this_week`/`slots_next_week`/`open_loop_free_next`,
не трогая посторонний `template`. Добавлено в оба успешных пути эндпоинта (per-slot
точный режим и обычный режим часов).
Verified at: working tree (не закоммичено), 2026-09-03

### AC-006
Клиентский фолбэк-построитель подсказок не показывает то, что отклонено на сервере.
Requirement: CONFIRMED
Verification method: e2e
Capability: playwright
Result: VERIFIED
Evidence: полный браузерный e2e через Playwright не проведён — тот же пробел, что в
TASK-028 S2/S4 (нет мока Telegram initData для мини-аппа в этой сессии); честно понижено
до чтения кода + `node -c` (без синтаксических ошибок), как и было заранее решено в
Verification строке среза S4. По коду: фолбэк-путь (`buildHubInboxItemsFromClient`,
`rhythmCands.forEach`, :2086) фильтрует кандидатов через тот же вызов
`isRhythmHintDismissed(cand.id)`, что и основной путь (:2101) — единая точка правды, не
дублирующая логика. Для 6 allowlist-id эта функция читает `hubOnboardingData.active_hint_snoozes`
(серверные данные), а не localStorage — фолбэк физически не может показать отклонённое на
сервере. Для `open_loop_no_next`/`slots_this_week` `isRhythmHintDismissed` теперь всегда
возвращает `false` (`HUB_URGENT_NON_DISMISSIBLE_HINT_IDS`), поэтому даже старая
localStorage-запись, оставшаяся с прошлой версии клиента, больше не может спрятать
срочную подсказку ни в одном из путей (DEC-005).
Verified at: working tree (не закоммичено), 2026-09-03

### AC-007
Приглашение в каталог продолжает работать как прежде: `catalog_invite_dismissed`
в чеклисте, `POST /trainer/onboarding/next-step/dismiss` отвечает 422 на чужой ключ.
Requirement: CONFIRMED
Verification method: integration
Result: VERIFIED
Evidence: старый эндпоинт не тронут (новый — отдельный, DEC-003); существующий
`test_catalog_invite_not_now_is_remembered_server_side` зелёный без изменений.
Verified at: working tree (не закоммичено), 2026-09-03

### AC-008
Полный прогон pytest не хуже базовой линии на момент старта задачи.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: baseline из TASK-028 S5 — 9 failed/1226 passed/6 skipped, тот же список падений,
что и в TASK-026/027 (пред существующие, не в файлах этих задач). С изменениями TASK-029 —
8 failed/1256 passed/3 skipped: 30 новых прошедших тестов, на 1 меньше падений, ноль новых.
Все 8 текущих падений (`test_webapp_client_miniapp_integration.py` ×3,
`test_trainer_profile_demotion.py`, `test_trainer_services_remove_guard.py` ×2,
`test_share_catalog_tip.py` ×2) — вне файлов, тронутых TASK-029 (`webapp.py`,
`trainer_hub_action_inbox.py`, `trainer_hint_dismissal_use_cases.py`, `models.py`,
`trainer-home-main.js`). Точечный прогон новых/изменённых файлов задачи —
`test_trainer_hint_dismissal.py` + `test_webapp_trainer_hub_inbox.py` +
`test_trainer_hub_action_inbox.py` + `test_trainer_next_step.py` — 62/62 зелёных.
Verified at: working tree (не закоммичено), 2026-09-03

## Edge Cases

### EDGE-001
У действующих тренеров отказы лежат в localStorage и на сервер не переедут. После
релиза часть подсказок вернётся один раз. Это приемлемо (подсказки не деструктивны),
но должно быть осознанным решением, а не сюрпризом.
Severity: LOW
Status: OPEN

### EDGE-002
Срочные подсказки (`urgent = true`: неподтверждённые записи, ученики без следующей
записи, пустая неделя) отказу подлежать не должны — иначе тренер спрячет реальную
проблему. Сейчас `dismissible` приходит с сервера (`_inbox_item`), это надо сохранить
и на уровне эндпоинта: отказ от неотклоняемой подсказки — 422.
Severity: HIGH
Status: RESOLVED
Resolution: подтверждено при /clarify — `open_loop_no_next` и `slots_this_week` имели
`urgent=True` и `dismissible=True` одновременно; переведены на `dismissible=False`
(DEC-004); эндпоинт `dismiss_rhythm_hint` отклоняет оба id и любой неизвестный —
`ValueError` → 422.
Verification: integration — `test_open_loop_no_next_and_slots_this_week_are_not_dismissible`,
`test_dismiss_rhythm_hint_raises_for_non_dismissible[open_loop_no_next]`,
`[slots_this_week]` — все зелёные.

### EDGE-003
Гонка: тренер жмёт «Не сейчас» и сразу закрывает мини-апп. Запрос может не уйти.
Решить, что важнее — оптимистичное скрытие на клиенте или отсутствие расхождения.
Severity: LOW
Status: OPEN

## Decisions

### DEC-001
Decision: Один эндпоинт отказа для всех подсказок, срок глушения назначает сервер
по `hint_id`, клиент срок не передаёт.
Reason: Срок — продуктовое правило, а не пожелание клиента. Держать его в JS означает,
что пуш-циклы в боте о нём не узнают, и мы снова получим два источника правды.
Alternatives: расширить существующий эндпоинт каталога — приемлемо, если он честно
переименован; недопустимо оставлять два разных механизма отказа.

### DEC-002
Decision: Срочные (`urgent`) подсказки не отклоняются в принципе, ни на клиенте,
ни на сервере.
Reason: Они описывают работу, которая блокирует живого человека — клиента, ждущего
подтверждения. Спрятанная такая подсказка — это потерянный клиент, а не тишина.

### DEC-003
Decision: Новый отдельный эндпоинт `POST /trainer/hub/rhythm-hint/dismiss` (тело
`{hint_id}`) для ритм-подсказок инбокса — существующий
`POST /trainer/onboarding/next-step/dismiss` не трогается и продолжает обслуживать
только карточку «следующий шаг» (`STEP_CATALOG_INVITE`).
Reason: Это два разных понятия с разными таблицами и разным пространством
идентификаторов (`key` карточки next-step vs `hint_id` строки инбокса) — «каталог» уже
переиспользует одно и то же поле `catalog_invite_dismissed_at` из обоих UI-мест
(next-step карточка и ритм-подсказка `catalog_publication`, см. Facts), так что
переезд каталога в новую таблицу не нужен (уже отмечено в Implications). AC-007
явно требует, чтобы старый эндпоинт продолжал работать «как прежде» — совмещать его
с новым смыслом означало бы менять его контракт.
Alternatives: один универсальный эндпоинт на оба понятия — отклонено: пришлось бы
ветвиться внутри по типу `key`/`hint_id`, что сложнее двух простых эндпоинтов и
рискует контрактом next-step (AC-007).

### DEC-004
Decision: `open_loop_no_next` и `slots_this_week` в `_build_hub_rhythm_inbox_candidates`
(`trainer_hub_action_inbox.py`) переводятся на `dismissible=False` — это и есть
исправление EDGE-002, найденное при `/clarify`. Список отклоняемых `hint_id` на новом
эндпоинте — статический allowlist из оставшихся: `referral_growth`,
`open_loop_free_next`, `slots_next_week`, `template`, `client_notes`,
`open_loop_no_telegram`. Запрос с любым другим `hint_id` (включая эти два урезанных
и любой неизвестный) — 422.
Reason: Оба поля `urgent=True` и `dismissible=True` одновременно на одном элементе —
прямое противоречие DEC-002, уже присутствующее в коде до начала этой задачи. Задача
явно называет это HIGH severity edge case для решения, а не для дальнейшего
воспроизведения в новом эндпоинте.

### DEC-005
Decision: Клиентский фолбэк-билдер (`buildHubRhythmCandidates`,
`trainer-home-main.js:1501`) для `open_loop_no_next` тоже перестаёт проверять
`isRhythmHintDismissed` — по DEC-002 «ни на клиенте, ни на сервере», а не только
на сервере.
Reason: Тот же принцип должен работать одинаково на обоих путях рендера, иначе
фолбэк-путь (используется, когда bootstrap не прислал action_inbox) даст тренеру
спрятать открытую проблему с клиентом, которую основной путь спрятать не позволит.
Alternatives: оставить как есть до TASK-034 (полное удаление фолбэка) — отклонено:
DEC-002 сформулирован без исключения для фолбэка, а расхождение поведения между
путями — ровно тот класс бага, который эта задача и закрывает.

## Design Context

Нет новой визуальной поверхности — существующие подсказки продолжают выглядеть
так же; меняется только откуда берётся решение «показывать или нет».

## Technical Plan

1. **Миграция + модель** `trainer_hint_dismissals (id, trainer_id FK CASCADE, hint_id
   String(32), dismissed_at timestamptz default now(), snooze_until timestamptz
   nullable)`, UNIQUE `(trainer_id, hint_id)`.
2. **`src/application/trainer_hint_dismissal_use_cases.py`** (новый модуль):
   - `DISMISSIBLE_HINT_DEFAULT_SNOOZE_DAYS: dict[str, int]` — `referral_growth`: 3,
     `open_loop_free_next`: 3, `template`: 10, `client_notes`: 10,
     `open_loop_no_telegram`: 10 (срок как у ближайшей по духу группы в JS — «growth»
     vs «long»); `slots_next_week` — 3 (ближе к growth: тот же ритм, что и slots).
   - `async def dismiss_rhythm_hint(session, trainer_id, hint_id) -> None` — 422
     (`ValueError`) если `hint_id` не в allowlist; иначе upsert `snooze_until = now()
     + N дней` (`ON CONFLICT ... DO UPDATE`).
   - `async def get_active_snoozes(session, trainer_id) -> dict[str, datetime]` —
     `{hint_id: snooze_until}` только для строк, где `snooze_until > now()`.
3. **`POST /trainer/hub/rhythm-hint/dismiss`** в `webapp.py` — тело `{hint_id: str}`,
   вызывает `dismiss_rhythm_hint`, 422 при `ValueError`.
4. **`_build_hub_rhythm_inbox_candidates`** (`trainer_hub_action_inbox.py`) —
   принимает уже вычисленный `active_snoozes: dict[str, datetime]` (пробрасывается из
   `build_trainer_hub_action_inbox`, которая сама получает его от вызывающего кода
   в `webapp.py`, аналогично текущему `catalog_invite_dismissed`), пропускает кандидата,
   если `hint_id in active_snoozes`. `open_loop_no_next` / `slots_this_week` —
   `dismissible=False` (DEC-004).
5. **Сброс при сохранении слотов** — найти текущий сброс
   (`webapp.py:1190` упоминается в Facts, проверить актуальную строку) и добавить
   `DELETE FROM trainer_hint_dismissals WHERE trainer_id=:tid AND hint_id IN
   ('slots_this_week','slots_next_week','open_loop_free_next')` рядом с существующим
   клиентским сбросом (оставить клиентский сброс как есть — снятие с клиента полного
   стораджа решений не входит в Scope этой правки, только сами снузы).
6. **Клиент** (`trainer-home-main.js`): `isRhythmHintDismissed` читает
   `hubOnboardingData.active_hint_snoozes` (новое поле bootstrap-ответа) вместо
   localStorage для 6 allowlist-id; `dismissHubInboxRhythmItem` шлёт
   `POST /trainer/hub/rhythm-hint/dismiss` вместо локальной записи; вызов
   `setRhythmDismissUntilMs`/localStorage для этих id удаляется. `open_loop_no_next`
   гейт `isRhythmHintDismissed` убирается из фолбэка (DEC-005).
7. **Бутстрап** — `GET /trainer/hub/bootstrap` и `GET /trainer/hub/inbox-count`
   прокидывают `active_hint_snoozes` в `onboarding`/ответ инбокса, читая
   `get_active_snoozes` рядом с существующим `catalog_invite_dismissed`.

## Test Strategy

- Новый `tests/application/test_trainer_hint_dismissal.py` — `dismiss_rhythm_hint`
  ставит `snooze_until` в будущее; неизвестный/urgent `hint_id` → `ValueError`;
  `get_active_snoozes` не возвращает истёкшие.
- `tests/application/test_trainer_hub_action_inbox.py` — расширить
  `_build_hub_rhythm_inbox_candidates`/`build_trainer_hub_action_inbox` тестами:
  переданный `active_snoozes` скрывает кандидата; `open_loop_no_next`/
  `slots_this_week` теперь `dismissible: False` в ответе.
- `tests/api/test_webapp_trainer_hub_inbox.py` — новый эндпоинт: успешный dismiss
  снузит подсказку в следующем bootstrap; dismiss неизвестного/urgent `hint_id` → 422.
- Интеграционный тест на сброс снуза при сохранении слотов (там же, где сейчас
  проверяется существующий клиентский сброс, или новый рядом).
- Регресс существующего эндпоинта каталога — уже есть тесты, прогнать без изменений
  (AC-007).
- Полный `pytest` + честная baseline-проверка (AC-008).

## Slices

### S1 Таблица, модуль, новый эндпоинт
Goal: сервер умеет принимать и хранить отказ от ритм-подсказки со сроком.
Scope: миграция `0185`, `models.py` (`TrainerHintDismissal`),
`trainer_hint_dismissal_use_cases.py`, `POST /trainer/hub/rhythm-hint/dismiss`.
Covers: AC-004 (частично — механизм срока), AC-007
Verification: `pytest tests/application/test_trainer_hint_dismissal.py
tests/api/test_webapp_trainer_hub_inbox.py` — 25 passed; регресс старого эндпоинта
каталога (`test_catalog_invite_not_now_is_remembered_server_side`) зелёный.
Estimate: 3
Status: DONE

### S2 Сервер читает отказы при сборке инбокса + EDGE-002
Goal: отклонённый кандидат не попадает в ответ; urgent-подсказки не отклоняются.
Scope: `trainer_hub_action_inbox.py` (`_build_hub_rhythm_inbox_candidates` принимает
`active_snoozes`, `dismissible=False` для `open_loop_no_next`/`slots_this_week`),
`webapp.py` (bootstrap, inbox-count, standalone checklist — все три прокидывают
`active_hint_snoozes`).
Depends on: S1
Covers: AC-001, AC-003, AC-004 (полностью)
Verification: 3 новых pure-теста в `test_trainer_hub_action_inbox.py` (19/19 в файле) +
1 сквозной API-тест через реальный dismiss → реальный bootstrap (17/17 в файле) +
regression `test_webapp_trainer_miniapp_profile_integration.py` (37/37).
Estimate: 3
Status: DONE

### S3 Сброс при сохранении слотов
Goal: сохранение слотов в редакторе снимает снуз с подсказок про слоты — как сейчас
на клиенте.
Scope: `_clear_slot_related_hint_snoozes` (новый хелпер) + оба успешных пути
`POST /schedule/slots` в `webapp.py`.
Depends on: S1
Covers: AC-005
Verification: `test_saving_slots_clears_slots_related_snoozes` + регресс
`test_webapp_trainer_schedule_integration.py` (38/38).
Estimate: 1
Status: DONE

### S4 Клиент: перевод на серверное состояние
Goal: `isRhythmHintDismissed`/`dismissHubInboxRhythmItem` используют сервер, не
localStorage, для 6 allowlist-id; `open_loop_no_next` фолбэка больше не отклоняется.
Scope: `trainer-home-main.js`.
Depends on: S2
Covers: AC-002 (другое устройство — просто следствие серверного хранения), AC-006
Verification: чтение кода + `node -c`; браузерный клик-тест не проводится (тот же
пробел, что в TASK-028 S2/S4 — нет мока Telegram initData в этой сессии).
Estimate: 3
Status: DONE

### S5 Регресс и базовая линия
Goal: старый эндпоинт каталога не задет; полный набор тестов не хуже базовой линии.
Scope: весь репозиторий.
Depends on: S1, S2, S3, S4
Covers: AC-007, AC-008
Verification: существующие тесты каталога-дисмисса зелёные; полный `pytest`,
сравнение со стабильным baseline (9 падений из TASK-026/027/028).
Estimate: 1
Status: DONE

## Next Action

Задача завершена. Открытые edge cases (EDGE-001, EDGE-003) остаются LOW/OPEN осознанно —
см. Edge Cases.

## Execution History

- **TASK_CREATED** — заведена 2026-09-02 по исследованию `.ai/RESEARCH-ACTIVATION-2026-09-02.md`, §P5.
- **PHASE_STARTED** — 2026-09-03 | clarify
- **PHASE_COMPLETED** — 2026-09-03 | clarify | Все 8 AC уже CONFIRMED, DEC-001/002 зафиксированы при заведении задачи. При чтении текущего кода найдено конкретное подтверждение EDGE-002 (уже HIGH, уже OPEN): `open_loop_no_next` и `slots_this_week` в `trainer_hub_action_inbox.py` имеют одновременно `urgent=True` и `dismissible=True` — прямое нарушение DEC-002 уже в проде. Открытых UNKNOWN нет.
- **PHASE_STARTED** — 2026-09-03 | plan
- **PHASE_COMPLETED** — 2026-09-03 | plan | 5 срезов; DEC-003 (новый отдельный эндпоинт, не трогаем существующий каталожный), DEC-004 (закрытие EDGE-002: dismissible=False для двух urgent id, статический allowlist для остальных 6), DEC-005 (тот же принцип в клиентском фолбэке).
- **PHASE_STARTED** — 2026-09-03 | estimate
- **PHASE_COMPLETED** — 2026-09-03 | estimate | 5 срезов, 11 story points (S1=3, S2=3, S3=1, S4=3, S5=1). Все 8 AC покрыты.
- **SLICE_VERIFIED** — 2026-09-03 | S1 | Миграция `0185`, модель `TrainerHintDismissal`, модуль `trainer_hint_dismissal_use_cases.py`, новый эндпоинт `POST /trainer/hub/rhythm-hint/dismiss`. 25 новых тестов (идемпотентность-апсерт, urgent/unknown → ValueError→422, истёкшие снузы не возвращаются, сброс списком). Старый эндпоинт каталога не тронут, регресс зелёный. AC-007 → VERIFIED.
- **SLICE_VERIFIED** — 2026-09-03 | S2 | `_build_hub_rhythm_inbox_candidates` фильтрует по `active_snoozes`; `open_loop_no_next`/`slots_this_week` переведены на `dismissible=False` (EDGE-002 RESOLVED). Все три места в `webapp.py`, читающие/собирающие чеклист и инбокс, прокидывают `active_hint_snoozes`. 1 сквозной end-to-end тест (реальный dismiss → реальный bootstrap) + 3 pure-теста + широкий регресс. AC-001, AC-003, AC-004 → VERIFIED.
- **SLICE_VERIFIED** — 2026-09-03 | S3 | `_clear_slot_related_hint_snoozes` вызывается из обоих успешных путей `POST /schedule/slots`. 1 новый тест + регресс 38/38 в файле расписания. AC-005 → VERIFIED.
- **SLICE_VERIFIED** — 2026-09-03 | S4 | `trainer-home-main.js`: `isRhythmHintDismissed` для 6 allowlist-id (`referral_growth`, `open_loop_free_next`, `slots_next_week`, `template`, `client_notes`, `open_loop_no_telegram`) читает серверный `hubOnboardingData.active_hint_snoozes` вместо localStorage; `dismissHubInboxRhythmItem` шлёт `POST /trainer/hub/rhythm-hint/dismiss` для тех же id (оптимистичное локальное обновление + fire-and-forget запрос), localStorage-путь остаётся только для `share_link`/`open_loop_free_next_growth`/`catalog_publication`/`subscription_lapsed`/прочих. DEC-005: `open_loop_no_next`/`slots_this_week` заведены в `HUB_URGENT_NON_DISMISSIBLE_HINT_IDS` — `isRhythmHintDismissed` для них теперь безусловно `false` (закрывает EDGE-002 и для фолбэк-пути, включая устаревшие localStorage-записи), а фолбэк-билдер (`buildHubInboxItemsFromClient`) больше не проставляет им `dismissible: true`. Верификация — чтение кода + `node -c` (без браузерного Playwright-прохода, тот же пробел, что в TASK-028 S2/S4, честно отмечено в AC-006). AC-002, AC-006 → VERIFIED.
- **SLICE_VERIFIED** — 2026-09-03 | S5 | Полный `pytest` с изменениями TASK-029: 8 failed/1256 passed/3 skipped против baseline из TASK-028 (9 failed/1226 passed/6 skipped) — на 1 меньше падений, ноль новых, 30 новых прошедших тестов. Все 8 текущих падений вне файлов задачи. Точечный прогон 4 файлов задачи — 62/62 зелёных. Старый эндпоинт каталога не тронут. AC-007, AC-008 → VERIFIED.
- **PHASE_COMPLETED** — 2026-09-03 | verify | Все 8/8 AC VERIFIED, все 5/5 срезов DONE.
- **REVIEW** — 2026-09-03 | 0 Critical/High, 2 Medium, 2 Low; все 4 исправлены по месту (не отдельным срезом). Medium: убран `trackHubGuidanceEvent('hint_dismissed', ...)` из `dismissHubInboxRhythmItem` (вне Scope, отдано TASK-028); `_build_hub_rhythm_inbox_candidates` теперь явно исключает `NON_DISMISSIBLE_URGENT_HINT_IDS` из фильтра по `active_snoozes` — защита появилась и на read-пути, не только на write (`dismiss_rhythm_hint`); тест `test_snooze_cannot_hide_an_always_urgent_hint_even_if_passed` перевёрнут на «выживает даже при гипотетическом снузе». Low: добавлен `test_saving_slots_via_per_slot_mode_also_clears_slots_related_snoozes` — второй успешный путь (`slot_entries`) теперь тоже покрыт; `_SLOT_RELATED_SNOOZE_HINT_IDS` избавлен от мёртвого `slots_this_week`. Полный `pytest` после правок: 8 failed (те же baseline)/1258 passed/3 skipped — ноль новых падений, +2 новых теста.
- **PHASE_COMPLETED** — 2026-09-03 | review | Чисто после исправлений — готово к COMPLETE.
