---
task_id: TASK-007
title: «Два шага — и первые клиенты» не выполняется, чеклист исчезает до попадания в каталог
status: COMPLETE
phase: review
created_at: 2026-08-31
updated_at: 2026-08-31T23:59:59Z
---

# Task

## Strategy

```yaml
strategy:
  state_required: true
  research_required: false
  clarification_required: true
  planning_required: true
  verification_level: elevated
```

Chain: `clarify → plan → implement → verify`

## Objective

Привести обещание онбординга в соответствие с результатом. Сейчас после обоих «Первых шагов» тренер не в каталоге, анкета не отправлена на модерацию, клиентов ноль — а полоса онбординга скрывается целиком, и реальный следующий шаг деградирует до закрываемой навсегда подсказки.

## Business Context

Тренер приходит за клиентами. Онбординг объявляет «Два шага — и первые клиенты появятся в расписании», после двух шагов клиентов появиться неоткуда, и продукт перестаёт вести его дальше. Самое важное действие воронки (фото → модерация → каталог) живёт в самом слабом слоте интерфейса.

## Scope

### In Scope

- Текст обещания в полосе «Первые шаги» (`static/webapp/trainer-home.html`)
- Условие скрытия полосы: `onboardingAllComplete` (`static/webapp/trainer-home-main.js`)
- Продвижение шага «попасть в каталог» из ритм-подсказки в явный шаг онбординга
- Разбор полурабочего состояния публичной карточки vs слотов для `pending_profile`

### Out of Scope

- Смена активационного действия на «отправь ссылку» — TASK-011
- Тексты гейтов и модерации — TASK-014

## Comprehension Tips

### Facts

- `static/webapp/trainer-home.html:372` — лид полосы: «Два шага — и первые клиенты появятся в расписании.» Шаги: «Расскажите о себе» и «Первый клиент» (`:378`, `:386`).
- `static/webapp/trainer-home-main.js:1404-1412` — `onboardingAllComplete`: для не-active достаточно `schedule_unlocked && tt_minimal_complete && любая запись`. При `true` (`:3027-3044`) полоса получает `hidden` и `display:none`.
- TTV-минимум — 5 критериев без фото, описания, образования (`src/application/trainer_profile_completeness.py::analyze_tt_minimal_profile_readiness`). Планка отправки на модерацию — 8 критериев, **фото обязательно**. Значит после двух шагов статус остаётся `pending_profile`, `moderation_submitted_at` пуст.
- `src/api/routes/public.py:647-662` — `GET /api/public/trainers/{id}` требует `status = active` и `is_catalog_visible`, иначе 404. То есть публичная карточка недоступна.
- Единственный оставшийся указатель — ритм-подсказка `catalog_publication` (`static/webapp/trainer-home-main.js:1830-1860`), `priority: 108`, попадает под общий кап growth-хинтов (`applyHubInboxRhythmCap`) и закрывается навсегда через `isRhythmHintDismissed`.
- Полурабочее состояние, требует проверки: `src/api/routes/webapp.py:1352-1364` — `GET /api/webapp/client/slots` проверяет `status = active` **только если** `trainer_allows_online_booking` вернул `False`. На триале включены все модули, значит слоты для `pending_profile` тренера отдаются. При этом `static/webapp/book.html:1011-1015` глотает 404 от `/api/public/trainers/{id}` в пустом `catch` — клиент по личной ссылке увидит страницу записи с рабочими слотами и пустой карточкой тренера.

### Implications

- Либо честно переформулировать обещание под то, что два шага реально дают (рабочее расписание для текущих учеников), либо добавить третий шаг «фото + отправка на проверку» и не скрывать полосу, пока тренер не в каталоге.
- Скрытие полосы при `!is_active` — самая дорогая строка: она обрывает ведение ровно на границе, где начинается ценность.
- Расхождение slots/catalog нужно решить осознанно в одну сторону: либо личная ссылка официально работает до модерации (тогда это фича, и её надо показывать — см. TASK-006), либо не работает (тогда 404 должен давать внятный экран, а не пустую карточку).

## Acceptance Criteria

- **AC-001** — Лид полосы «Первые шаги» обещает попадание в каталог за три шага, а не появление клиентов за два. Формулировка соответствует реальному результату прохождения всех шагов.
  Status: CONFIRMED (Q-003)
  Verification: manual / exploratory (проверка копирайта против фактического состояния тренера)

- **AC-002** — «Попасть в каталог» (фото + отправка на модерацию) присутствует как явный шаг полосы онбординга, а не только как ритм-подсказка `catalog_publication`.
  Status: CONFIRMED
  Verification: **изменён** с `automated / integration` на `manual / static` — JS-раннера в проекте нет, заводить его отдельный скоуп.

- **AC-003** — `onboardingAllComplete` для не-`active` тренера требует заполненного `moderation_submitted_at`, а не только «TTV-минимум + одна запись». Полоса не скрывается, пока анкета не отправлена на модерацию.
  Status: CONFIRMED (Q-001)
  Verification: бэкенд-половина — automated / integration (pytest); JS-предикат — manual / static.

- **AC-004** — Ритм-подсказка `catalog_publication` не дублирует новый явный шаг: она либо снимается, либо не показывается, пока шаг активен.
  Status: INFERRED
  Verification: **изменён** на `manual / static` (та же причина).

- **AC-005** — Счётчик прогресса (`onboardingProgressPill`, «Шаг 1 из 2») и логика подсветки шагов согласованы с новым количеством шагов.
  Status: INFERRED
  Verification: **изменён** на `manual / static` (та же причина).

- **AC-006** — Онбординг не обещает работающую публичную карточку или личную ссылку до попадания в каталог: тексты шагов не противоречат тому направлению, которое выберет TASK-006. Само расхождение слоты/карточка здесь не чинится.
  Status: CONFIRMED (Q-002)
  Verification: manual / exploratory (ревью копирайта шагов)

## Technical Plan

### Approach

Полоса становится трёхшаговой: профиль → первая запись → отправка на модерацию. Бэкенд отдаёт в чеклист один новый флаг `moderation_submitted` (уже вычисляется как `already_submitted_for_moderation`), фронт добавляет третий шаг и ужесточает `onboardingAllComplete` для не-`active`. Ритм-подсказка `catalog_publication` глушится, пока шаг виден, чтобы не дублировать ведение.

### Changes

1. **`src/application/trainer_onboarding_checklist.py`** — добавить в payload `moderation_submitted: bool(readiness.get("already_submitted_for_moderation"))`. В ветке `STUDIO_ACCESS_MODE_ADMIN_ONLY` форсировать `True` рядом с существующими `profile_complete`/`has_any_booking` — иначе тренеры студии получат полосу, которую нечем закрыть. (AC-003)

2. **`static/webapp/trainer-home.html`** — лид `:372` под три шага и каталог вместо «Два шага — и первые клиенты появятся в расписании» (AC-001). Новый `<li id="onboardingStepCatalog">` с иконкой/названием/хинтом/CTA по образцу существующих шагов (AC-002). CTA шага бьёт в существующий `POST /trainer/onboarding/submit-for-moderation`; когда критериев не хватает — ведёт в профиль. Тексты не обещают работающую ссылку или карточку до каталога (AC-006).

3. **`static/webapp/trainer-home-main.js`**
   - `onboardingAllComplete` (`:1404`): в не-`active` ветке добавить `&& data.moderation_submitted`. Ветка `is_active && profile_complete` не трогается. (AC-003)
   - `shouldShowHubBookFab` (`:8407`, `:8413`) — **регрессия**: FAB висит на `onboardingAllComplete` и с новым предикатом пропадёт у тренера, прошедшего шаги 1–2. Перевести на `onboardingBookingStepDone`, что и было исходным смыслом («strip CTAs own the first-booking flow»).
   - Рендер полосы (`:3044+`): блок состояний третьего шага — не готов к отправке (CTA «Заполнить профиль») / готов (CTA «Отправить на проверку») / отправлен (`done`, без CTA) / вернулся с фидбеком (снова действие). (AC-002, edge cases)
   - Пилюля (`:3089-3090`): вместо тернарника `'Шаг 2 из 2' : 'Шаг 1 из 2'` — счёт выполненных из трёх. (AC-005)
   - `buildHubRhythmCandidates` (`:1829`): не пушить `catalog_publication`, пока полоса видна (`hubOnboardingStripVisible()`); хинт остаётся только для `active` тренеров с выключенной видимостью в каталоге. (AC-004)

### Data/API

Новых эндпоинтов нет. `GET /trainer/onboarding/checklist` получает одно поле `moderation_submitted`. Семантика существующих полей не меняется — важно, что `profile_complete` означает «готов к отправке» (8 критериев), а не «отправлен»; текущий копирайт хинта `catalog_publication` («Профиль отправлен на проверку» при `profile_complete`) на этом и врёт, новый шаг обязан различать эти состояния.

### Tests

- `onboardingAllComplete`: не-`active` с TTV+записью, но без `moderation_submitted` → `false`; с ним → `true`; `active && profile_complete` → `true` как раньше. (AC-003)
- Чеклист-эндпоинт: `moderation_submitted` присутствует; `ADMIN_ONLY` тренер получает `True`. (AC-003)
- Полоса для `pending_profile` с пройденными шагами 1–2 показывает третий шаг и не скрыта. (AC-002)
- `catalog_publication` не появляется одновременно с видимой полосой. (AC-004)
- Пилюля показывает «из 3». (AC-005)

### Risks

- **Регрессия FAB** — главный риск, снят пунктом 3.2; без него ужесточение предиката молча отбирает кнопку записи.
- **Тренеры студии** (`ADMIN_ONLY`) намеренно минуют сольный онбординг — без форса флага полоса станет для них вечной.
- **Уже `active` тренеры** не затронуты: их ветка предиката не меняется.
- `already_submitted_for_moderation` становится `False` при появлении `moderation_feedback` — это и даёт нужное поведение «модерация отклонила → шаг снова действие», но означает, что полоса у такого тренера вернётся. Поведение желаемое, но заметное.

## Verification Results

Прогон 2026-08-31 против `trainer_crm_test` (существовала, на head-ревизии `0176_care_pulses`; боевая `trainer_crm` не затрагивалась, `.env` не редактировался — DSN подменялся только в окружении процесса pytest).

| AC | Итог | Чем подтверждён |
|----|------|-----------------|
| AC-001 | VERIFIED | Ревью копирайта: лид заменён на «Три шага — и вы попадёте в каталог…» |
| AC-002 | VERIFIED (static) | `<li id="onboardingStepCatalog">` внутри `<ol>`; все 4 id резолвятся в JS; `wireOnboardingHub()` вызывается (`:8810`); роут `POST /trainer/onboarding/submit-for-moderation` существует |
| AC-003 | VERIFIED | **Бэкенд:** `test_trainer_onboarding_catalog_step.py` — 2 passed; ADMIN_ONLY-ассерт в `test_collective_w5_admin.py` — 6 passed. **JS:** предикат прочитан, ветка `is_active` не тронута |
| AC-004 | VERIFIED (static) | Гард `!hubOnboardingStripVisible()` в `buildHubRhythmCandidates` |
| AC-005 | VERIFIED (static) | `focusStep` даёт «Шаг N из 3»; мёртвая ветвь тернарника убрана |
| AC-006 | VERIFIED | Ревью копирайта: тексты шагов не обещают ссылку/карточку до каталога |

**Регрессия не внесена.** `tests/application` + `tests/api` на дереве с изменениями: `15 failed, 689 passed`. Тот же набор на дереве, откаченном до HEAD: `15 failed, 687 passed`. Падают одни и те же 15 тестов в `tests/api/test_webapp_client_miniapp_integration.py` — они **предсуществующие** (загрязнение состояния между тестами: поштучно проходят), к этой задаче отношения не имеют. Разница `+2` — новые тесты этой задачи.

**Чего проверка НЕ покрывает:** мини-апп не запускался — хаб гейтится на Telegram `initData`. Пять из шести критериев подтверждены чтением кода и сверкой идентификаторов, а не наблюдением работающего интерфейса. Нужен ручной прогон в Telegram: тренер `pending_profile` с закрытыми шагами 1–2 должен увидеть полосу с третьим шагом, а не пустой хаб.

## Edge Cases

- Тренер уже `active` — полоса не должна вернуться для тех, кто прошёл путь до изменения.
- Тренер отправил анкету и ждёт модерацию (дни): шаг 3 должен иметь непрерывное «на проверке» состояние, а не выглядеть недоделанным.
- Модерация отклонила анкету — шаг снова должен стать действием, а не тупиком.

## Open Questions

Все вопросы этой фазы закрыты (ответы человека 2026-08-31):

- **Q-001** — RESOLVED: полоса скрывается по заполненному `moderation_submitted_at`. Тренер сделал всё, что от него зависит; ожидание модерации — не его задача, о публикации сообщит отдельное уведомление.
- **Q-002** — RESOLVED: расхождение слоты/карточка остаётся за TASK-006. TASK-007 трогает только полосу онбординга и обязан лишь не противоречить будущему решению.
- **Q-003** — RESOLVED: цель — довести тренера до каталога, три шага. Обещание не снижается.

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **PHASE_STARTED** | clarify — черновик Acceptance Contract
- **HUMAN_GATE** | clarify — AC-003 и AC-006 были UNKNOWN до ответов на Q-001 и Q-002
- **PHASE_COMPLETED** | clarify — Q-001/Q-002/Q-003 отвечены человеком, все шесть AC переведены в CONFIRMED/INFERRED, блокирующих UNKNOWN не осталось
- **PHASE_STARTED** | plan — построение технического плана
- **PHASE_COMPLETED** | plan — 3 файла, 4 среза; найдена регрессия FAB (shouldShowHubBookFab висит на onboardingAllComplete) и ветка ADMIN_ONLY, обе учтены
- **PHASE_STARTED** | implement — четыре среза плана
- **PHASE_COMPLETED** | implement — бэкенд-флаг `moderation_submitted` (+ форс в ADMIN_ONLY), третий шаг в разметке, предикат/пилюля/рендер/CTA, глушение хинта `catalog_publication`, перевод FAB на `onboardingBookingStepDone`, bump `?v=` до 202608310. Написаны 2 новых теста + 1 assert в существующий.
- **HUMAN_GATE** | verify — тесты НЕ выполнены: postgres недоступен (docker-демон не запущен, локального сервера нет, порт 5432 закрыт), JS-раннера в проекте нет вовсе. Проверено только `node --check` и `py_compile`. Ни один AC не может быть переведён в VERIFIED без прогона.
- **PHASE_STARTED** | verify — база поднята пользователем
- **PHASE_COMPLETED** | verify — 6/6 AC VERIFIED (AC-003 бэкенд тестами, остальные ревью/статикой). Метод проверки AC-002/004/005 понижен с automated на manual/static: JS-раннера в проекте нет. Регрессия исключена сравнением с baseline на откаченном дереве.
- **REVIEW** — 1 Medium, 2 Low. Medium: 422 от `/trainer/onboarding/submit-for-moderation` — `postJsonTrainer` стрингифицирует объект `detail` в `"[object Object]"`, шаг 3 CTA показывает это тренеру через `hubToast` вместо `missing_labels_ru`. Low: «на проверке» состояние шага 3 недостижимо в естественном порядке 1→2→3 (полоса прячется в тот же тик); ритм-подсказка `catalog_publication`, ранее закрытая тренером, не переоткроется как единственный оставшийся сигнал.
- **PHASE_STARTED** | implement — фикс Medium-находки ревью
- **PHASE_COMPLETED** | implement — `postJsonTrainer` (`trainer-home-main.js:428`) сохраняет структурированный `detail` на `Error` вместо стрингификации объекта; CTA шага 3 (`:3403`) теперь показывает `missing_labels_ru` при 422. `node --check` чист. Оба Low-находки (недостижимое «на проверке» состояние, dismissal ритм-хинта) оставлены как есть — не баги, решение см. в ревью и в диалоге с пользователем.
- **HUMAN_GATE** | verify — повторный прогон `test_trainer_onboarding_catalog_step.py` + `test_collective_w5_admin.py` на `trainer_crm_test` даёт `asyncpg.exceptions.UndefinedColumnError: column "arena_work_format" does not exist` (3 failed, 5 passed) — было 8/8 passed в этой же сессии до этого. Причина не в фиксе: параллельно в рабочем дереве появились несвязанные `migrations/versions/0177_welcome_trial_14_days.py`, `0178_trainer_arena_setup.py` и правки `src/infrastructure/db/models.py` (чужая незакоммиченная работа поверх той же БД) — `trainer_crm_test` не мигрирована на head, модель уже требует новую колонку. JS-фикс синтаксически чист (`node --check`), но backend-регрессию для AC-003 сейчас подтвердить нельзя без апгрейда тестовой БД, что вне скоупа этой задачи.
- **PHASE_STARTED** | verify — по разрешению пользователя синхронизирована `trainer_crm_test`: `alembic upgrade head` с явным `DATABASE_URL`+`DATABASE_URL_SYNC`, указывающими на `trainer_crm_test` (боевая `trainer_crm` уже была на head 0178, не трогалась, `.env` не редактировался). `0176_care_pulses` → `0178_trainer_arena_setup`.
- **PHASE_COMPLETED** | verify — `test_trainer_onboarding_catalog_step.py` + `test_collective_w5_admin.py`: 8/8 passed. Полный `tests/application` + `tests/api`: 15 failed, 698 passed, 66 skipped — те же предсуществующие 15 падений в `test_webapp_client_miniapp_integration.py`, что и в исходном verify-прогоне; новых регрессий нет. Фикс Medium-находки ревью подтверждён, регрессии не внесены.
- **REVIEW** — чисто. Medium-находка (стрингификация `detail` в `[object Object]`) закрыта и подтверждена: `postJsonTrainer` сохраняет структурированный `detail`, CTA шага 3 показывает `missing_labels_ru`. 2 Low остаются как принятое поведение (см. предыдущую REVIEW-запись), не блокируют. Human Gate «Final review» открыт для решения пользователя.
- **COMPLETE** — пользователь одобрил. 6/6 AC VERIFIED, все Human Gates пройдены.
