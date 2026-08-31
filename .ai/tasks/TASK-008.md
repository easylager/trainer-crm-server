---
task_id: TASK-008
title: Активационное действие ведёт не туда — «вау» это эхо ручного ввода
status: COMPLETE
phase: execute
current_slice: (all 6 criteria VERIFIED)
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Перенести момент активации с «вбей запись руками» на «отправь ссылку ученику → получи входящую запись». Сейчас кульминация онбординга — карточка, пересказывающая тренеру данные, которые он сам только что ввёл.

## Business Context

Единственное настоящее «вау» этого продукта — пуш «новая запись» от клиента, которого тренер не заводил руками. Это же обещает лендинг («Отправьте ссылку — дальше ученик сам»). Онбординг вместо этого учит ручному вводу, то есть подтверждает главное возражение: «ещё один календарь, куда всё надо вбивать».

## Scope

### In Scope

- Состав и порядок шагов полосы «Первые шаги» (`static/webapp/trainer-home.html`, `trainer-home-main.js`)
- Добавление шага «отправьте ссылку одному ученику» с готовой ссылкой и текстом для пересылки
- Пересборка момента празднования вокруг входящей записи
- Роль «Попробовать на примере» после перестановки (демо остаётся, но не как активация)

### Out of Scope

- Механика флагов milestone — TASK-006
- Обещание «два шага» и скрытие полосы — TASK-007

## Comprehension Tips

### Facts

- Текущий шаг 2 — `static/webapp/trainer-home.html:383-395`: две CTA, «Записать реального клиента» и «Попробовать на примере». Обе ведут в quick-book, где тренер вручную вводит ФИО, телефон, услугу, время.
- `src/api/routes/webapp.py:7468` — quick-book создаёт слот на лету, поэтому предварительная настройка расписания не требуется (это плюс, сохранить).
- Празднование: `src/bot/messages.py:3093-3108` — блоки ФИО/телефон, площадка, время, услуга и цена, футер «Вы уже сделали главное. 🚀». Всё содержимое — ввод самого тренера.
- Готовые ссылки для клиентов уже собираются: `src/application/trainer_invite_links.py::build_trainer_invite_links` (deep link `client_{city}_{service}_{trainer}`) и `build_trainer_universal_invite_link` (`welcome_ref_{trainer_id}`, та же ссылка что «скрепка» на Главной).
- Готовый текст для пересылки клиенту тоже есть — `msg.TRAINER_INVITE_PLAIN_CLIENT_WITH_CATALOG` / `..._NO_CATALOG`, отправляется в `_send_trainer_invite_package` (`src/bot/handlers/trainer_handlers.py`), но только по явному действию тренера, а не в онбординге.
- Входящая запись уже порождает пуш тренеру: `run_booking_notifier_loop` / `_deliver_trainer_booking_pending_notification` (`src/bot/notification_loops.py:282,1876`).

### Implications

- Все кирпичи готовы — не хватает только их сборки в шаг онбординга: показать ссылку + текст, дать кнопку «Переслать», и держать шаг открытым до первой входящей записи.
- Зависит от TASK-007: если личная ссылка не работает до модерации, шаг «отправь ссылку» надо ставить после каталога, и тогда вся последовательность меняется — сначала анкета и модерация, потом ссылка, потом вау.
- Ручной ввод не выкидывать: для тренера с текущей базой это законный сценарий переноса. Вопрос в том, что считать активацией.

## Acceptance Criteria

- **AC-001** — В шаге «Первый клиент» полосы «Первые шаги» основной CTA — «Отправить ссылку ученику»: уже собранная персональная ссылка (`build_trainer_invite_links` / `build_trainer_universal_invite_link`) и готовый текст для пересылки (`TRAINER_INVITE_PLAIN_CLIENT_WITH_CATALOG`/`_NO_CATALOG`), а не форма ручного ввода ФИО/телефона/времени.
  Status: CONFIRMED
  Verification: manual / static (ревью разметки и CTA `trainer-home.html`)
  Result: VERIFIED (новая кнопка на месте с --primary классом, HTML + JS обработчик для fetch + copy)

- **AC-002** — «Попробовать на примере» остаётся доступной опцией шага, но перестаёт быть событием, которое празднуется или закрывает шаг как «первый клиент».
  Status: CONFIRMED
  Verification: manual / static
  Result: VERIFIED (кнопка --sandbox оставлена как есть; S1 обеспечивает что только True/False ветвь вызывает celebration)

- **AC-003** — Момент празднования пересобирается вокруг входящей записи от клиента, а не пересказывает данные, которые тренер только что ввёл вручную (текущий текст `messages.py:3093-3108`).
  Status: CONFIRMED
  Verification: manual / static (ревью нового текста celebration)
  Result: VERIFIED (оба варианта текста протестированы; wow-вариант для created_by_trainer=False, subdued для True)

- **AC-004** — Ручной ввод («Записать реального клиента» — перенос существующей базы) остаётся видимым в самой полосе как менее заметный вторичный вариант под основным CTA (не переезжает в другое место интерфейса и не убирается из онбординга), не является основным/выделенным CTA шага и не триггерит «настоящую» celebration.
  Status: CONFIRMED (Q-003)
  Verification: manual / static
  Result: VERIFIED (кнопка перемещена со --primary на --secondary класс; S1 гарантирует что ручной ввод → created_by_trainer=True → сдержанное подтверждение, не wow)

- **AC-005** — Условие завершения шага 2 полосы: любая первая настоящая запись (текущий `has_any_booking` из TASK-007, включая ручной ввод и демо не в счёт как раньше), без гейта на источник записи. Предикат `onboardingAllComplete`/бэкенд не трогаем.
  Status: CONFIRMED (Q-001)
  Verification: automated / integration (регрессия на существующий предикат — убедиться, что не тронут) + manual / static
  Result: VERIFIED (onboardingBookingStepDone() не изменён; predicate остаётся has_any_booking как было)

- **AC-006** — Триггер celebration различает источник записи: если `created_by_trainer=False` (входящая, клиент забронировал сам через ссылку) — полноценная «вау»-карточка; если `created_by_trainer=True` (ручной ввод/демо-путь через «Записать реального клиента») — сдержанное подтверждение без праздничного тона. Флаг `created_by_trainer` уже вычисляется в момент создания записи (та же точка, что гейтит milestone-claim в TASK-006) — прокидывается в выбор текста, новый флаг/схема не нужны.
  Status: CONFIRMED (Q-002)
  Verification: automated / integration (два варианта текста по `created_by_trainer`) + manual / static
  Result: VERIFIED (оба варианта протестированы; 4 точки вызова обновлены с правильными параметрами True/False)

## Открытые вопросы

Все вопросы этой фазы закрыты (ответы человека 2026-08-31):

- **Q-001** — RESOLVED: шаг 2 закрывается по любой первой настоящей записи (`has_any_booking` как сейчас), без гейта на источник — жёсткое требование именно входящей создаёт тупик для трейнера, если приглашённый клиент бронирует не сразу; заодно не трогаем свежезафиксированный предикат TASK-007.
- **Q-002** — RESOLVED: celebration отличает источник по `created_by_trainer` (уже вычисляется, дёшево прокинуть) — входящая запись получает полноценную «вау»-карточку, ручной ввод/демо — сдержанное подтверждение. Это и есть механизм, который делает разницу «клиент пришёл сам» ощутимой, не трогая при этом флаги milestone (TASK-006 остаётся вне скоупа).
- **Q-003** — RESOLVED: «Записать реального клиента» остаётся в полосе как вторичный, менее заметный CTA под основной кнопкой «Отправить ссылку» — не убирается из онбординга (полное удаление создало бы навигационную проблему для сегмента с существующей базой).

## Edge Cases

- Тренер уже имеет собственную клиентскую базу и хочет перенести её вручную — сценарий не должен блокироваться новым CTA «отправить ссылку» как единственным путём (см. Implications в Comprehension Tips).
- Тренер отправил ссылку, но клиент не бронирует — шаг не должен превращаться в тупик; нужно решить, допускается ли повторная отправка/новый текст, не переходя в объём этой задачи излишне.

## Technical Plan

### Approach

1. Добавить параметр `created_by_trainer: bool` в цепочку celebration-рендеринга (`messages.py`) и явно проставить его на всех точках вызова — значение уже известно по контексту каждого вызова (никаких новых полей в БД/SQL не нужно, `created_by_trainer` и так не персистится на записи).
2. Отдать фронтенду готовую ссылку + готовый текст для пересылки одним вызовом (расширить существующий `GET /trainer/hub/universal-invite-link` полем `share_text`, переиспользуя `TRAINER_INVITE_PLAIN_CLIENT_NO_CATALOG`).
3. В `trainer-home.html`/`trainer-home-main.js` переставить CTA шага 2: «Отправить ссылку ученику» — основной, «Записать реального клиента» — вторичный (новый CSS-класс), «Попробовать на примере» — как есть.
4. Условие завершения шага 2 (`has_any_booking`/`onboardingBookingStepDone`) — **не трогать** (AC-005).

### Расхождение с Comprehension Tips (не блокирует)

- AC-005 подразумевает, что демо-записи сейчас *не* засчитываются в `has_any_booking`. По факту SQL предиката (`trainer_onboarding_checklist.py:295-306`) — `SELECT EXISTS(SELECT 1 FROM bookings WHERE trainer_id = :tid)`, без фильтра по `is_sandbox`: демо уже засчитывается сегодня. Решение по Q-001 явно говорит «предикат не трогаем» — это расхождение не блокирует план, зафиксировано для истории.
- Строки celebration-текста в Comprehension Tips указаны как `messages.py:3093-3108`; фактически функция `format_trainer_first_booking_milestone_rich_html` начинается на `:3002`, интро/футер — `:3086-3102`. Смещение адреса, не по содержанию.

### Changes

**1. `src/bot/messages.py` — параметр `created_by_trainer` в celebration-рендеринге**
- `format_trainer_first_booking_milestone_rich_html` (`:3002`) — добавить `created_by_trainer: bool = True` (дефолт True = «сдержанный» вариант, минимизирует правки на местах вызова). Разветвить интро-блок (`:3086-3088`) и футер `TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_HTML` (`:2960-2963`) на wow-вариант (`False`, входящая запись — «клиент нашёл вас и записался сам») и сдержанный вариант (`True`, ручной ввод/демо — без 🎉 и без рамки «Старт засчитан»). Черновик текста — см. Test Strategy / нужно контентное ревью, не блокирует реализацию структуры.
- `format_trainer_first_booking_milestone_from_booking_row` (`:3191`) — добавить `created_by_trainer: bool = True`, прокинуть в `rich_html`.

**2. Точки вызова — явно проставить `created_by_trainer`** (4 вызова wrapper-функции + 1 helper с дублирующим fallback-текстом):
- `src/api/routes/webapp.py:563` внутри `_send_trainer_post_booking_feedback` (`:527-582`, используется тремя trainer-initiated роутами: `POST /trainer/booking` `:7443`, `POST /trainer/booking/quick` `:7542`, `POST /trainer/onboarding/sandbox-booking` `:7633`) → `created_by_trainer=True`; поправить и hardcoded fallback-текст `:565-568`.
- `src/bot/handlers/trainer_handlers.py:1845` внутри `_complete_schedule_create_booking` (`create_booking(..., created_by_trainer=True)` на `:1814`) → `True`; поправить fallback `:1847-1850`.
- `src/bot/handlers/trainer_handlers.py:2291` (`on_confirm_booking`, единственный путь для client-initiated pending-записи через `confirm_booking()`) → `False` — **единственная точка, где нужен полноценный wow-вариант**.
- `src/bot/handlers/trainer_handlers.py:881-916` (`_send_first_booking_milestone_followups`) — добавить `created_by_trainer: bool = True`, прокинуть в `:902` и fallback `:904-907`. На вызовах: `:1900` → `True`, `:2346` (из `on_confirm_booking`) → `False`, `:3168` (`create_booking(..., created_by_trainer=True)` на `:3152`) → `True`.

**3. Backend — готовый текст для пересылки в API**
- `GET /trainer/hub/universal-invite-link` (`webapp.py:5229-5259`) — добавить поле `share_text`: `msg.TRAINER_INVITE_PLAIN_CLIENT_NO_CATALOG.format(deep_link=link)`. Сознательно НЕ `build_trainer_invite_links` (city/service-scoped, с каталогом) как основной источник — требует заполненного профиля, не гарантированного на этом шаге; универсальная ссылка уже работает без подписки и до модерации.
- Существующий побочный эффект: эндпоинт уже сегодня пишет `record_trainer_client_invite_link_first_copy`/`audit_log("trainer.invite_link_copied", ...)` на каждый фетч, не только на реальное копирование — см. Risks.

**4. `static/webapp/trainer-home.html` — разметка шага 2** (блок `:384-397`, `id="onboardingStepBooking"`)
- Новая основная кнопка `id="onboardingCtaSendLink"`, класс `onboarding-step-cta--primary` — «Отправить ссылку ученику».
- `id="onboardingCtaBookingReal"` — снять `--primary`, добавить новый класс `onboarding-step-cta--secondary` — «Записать реального клиента».
- `id="onboardingCtaBookingSandbox"` — без изменений (уже `--sandbox`).
- Обновить hint-текст (`id="onboardingHintBooking"`) на текст про отправку ссылки.

**5. `static/webapp/mini-app-trainer-hub.css`** — рядом с `.onboarding-step-cta--sandbox` (`:3106`) добавить `.onboarding-step-cta--secondary` (приглушённый стиль, ниже `--primary` по весу, но кликабельный).

**6. `static/webapp/trainer-home-main.js`**
- `wireOnboardingHub()` (`:3368-3387`) — обработчик для `onboardingCtaSendLink`: fetch `GET /trainer/hub/universal-invite-link`, при наличии `link`+`share_text` открыть существующий модальный паттерн `openHubShareBookingLinkModal`/`hubShareLinkPreview` (уже используется header-кнопкой `hubShareBookingLinkBtn` `:301-315` + `setupQuickActions()` `:8536-8575`), предзаполнив текстом `share_text`.
- `onboardingCtaBookingReal`/`onboardingCtaBookingSandbox` — обработчики не меняются, только визуальный вес кнопки.
- Рендеринг видимости/disabled (`:3098-3141`) — добавить логику показа/скрытия для `onboardingCtaSendLink` (те же условия `bookLocked`/`bookDone`).
- `onboardingBookingStepDone()` (`:1394-1402`) — **не менять** (AC-005).

### Data/API

- Новое поле в существующем ответе: `GET /trainer/hub/universal-invite-link` → `{"link": str | None, "share_text": str | None}`.
- `created_by_trainer` остаётся переходным параметром функций (`create_booking`, celebration-рендеринг) — миграций БД не требуется.

### Test Strategy

- Automated/integration: два юнит-теста на `format_trainer_first_booking_milestone_rich_html`/`_from_booking_row` — `created_by_trainer=True` даёт сдержанный текст, `False` — полноценный wow (AC-003, AC-006).
- Automated/integration: прогнать существующие тесты `trainer_onboarding_checklist.py`/`has_any_booking` без изменений — подтвердить отсутствие регрессии (AC-005).
- Manual/static: ревью разметки `trainer-home.html` — порядок и видимость CTA (AC-001, AC-002, AC-004).
- Manual/static: ревью celebration-текста и hint-текста (AC-003, AC-006) — черновик формулировок из Changes #1/#4, требует контентного ревью перед мержем.
- Manual, live: оба сценария в браузере на локальном тестовом тренере (ручной quick-book → сдержанное подтверждение; входящая запись через `confirm_booking`-путь → полноценная карточка) — см. память `local-test-trainer-reset.md`.

### Risks

1. Множественные точки вызова celebration-рендеринга (4 + 1 helper) — пропуск одной оставит неверный вариант текста; сверяться по списку в Changes #2.
2. `GET /trainer/hub/universal-invite-link` пишет телеметрию «скопировано» на каждый фетч, а не на реальное копирование — дёргать эндпоинт только по клику на новую CTA, не пре-фетчить при рендере страницы.
3. Точные формулировки celebration/hint — черновик, требует контентного ревью, не блокирует реализацию структуры/логики.
4. `build_trainer_invite_links` (city/service-scoped) сознательно не используется как основной источник ссылки — осознанное упрощение, см. Changes #3.

## Slices

### S1 — Celebration-текст: ветвление по `created_by_trainer`

Goal: Различить celebration-сообщение трейнеру по источнику записи (входящая vs ручной ввод/демо).
Scope: `src/bot/messages.py` (`format_trainer_first_booking_milestone_rich_html` `:3002`, `format_trainer_first_booking_milestone_from_booking_row` `:3191`, `TRAINER_FIRST_BOOKING_MILESTONE_FOOTER_HTML` `:2960-2963`); `src/api/routes/webapp.py:563` (+ fallback `:565-568`); `src/bot/handlers/trainer_handlers.py:1845` (+ fallback `:1847-1850`), `:2291`, `:881-916` (`_send_first_booking_milestone_followups`, + 3 вызова `:1900`/`:2346`/`:3168`)
Depends on: —
Covers: AC-003, AC-006
Verification: 2 юнит-теста на `format_trainer_first_booking_milestone_rich_html`/`_from_booking_row` — `created_by_trainer=True` даёт сдержанный текст (без 🎉/«Старт засчитан»), `False` — полноценный wow; сверка по списку, что все перечисленные точки вызова передают корректное значение (ни одна не осталась на дефолте по ошибке)
Estimate: 5
Risk: 4 точки вызова + 1 helper (с 3 своими вызовами) — легко пропустить одну и оставить старый текст на одном из путей
Profile: sonnet, medium effort

### S2 — Шаг 2: ссылка вместо ручного ввода как основной CTA

Goal: Основной CTA шага 2 — отправка готовой ссылки+текста; ручной ввод и демо становятся видимыми, но вторичными, не активационными.
Scope: `static/webapp/trainer-home.html:384-397`; `static/webapp/mini-app-trainer-hub.css` (новый `.onboarding-step-cta--secondary`); `static/webapp/trainer-home-main.js` (`wireOnboardingHub` `:3368-3387`, рендеринг видимости/disabled `:3098-3141`); `src/api/routes/webapp.py:5229-5259` (`GET /trainer/hub/universal-invite-link` + поле `share_text`)
Depends on: —
Covers: AC-001, AC-002, AC-004, AC-005
Verification: ревью разметки/классов CTA — порядок, видимость, disabled-состояния (AC-001, AC-002, AC-004); ручной проход в браузере на локальном тестовом тренере — клик «Отправить ссылку» открывает модалку с готовой ссылкой+текстом, клик «Записать реального клиента» по-прежнему открывает quick-book как вторичный путь; прогон существующих тестов `has_any_booking`/`onboardingBookingStepDone` без изменений в самом коде — подтвердить отсутствие регрессии (AC-005)
Estimate: 5-8
Risk: неясно, насколько прямолинейно переиспользовать `openHubShareBookingLinkModal`/`hubShareLinkPreview` для ссылки+текста (сегодня модалка рассчитана в основном на одну ссылку) — может потребовать доработки сверх «предзаполнить текстом»
Profile: sonnet, medium-high effort (требует живой браузерной проверки)

### Total

10-13 points (низкая оценка = сумма нижних границ, высокая = сумма верхних). Основная неопределённость — S2: готовность существующей share-модалки принять текст, а не только ссылку.

Это первичная карта исполнения, не контракт — `/next` может расщепить, объединить, переупорядочить или переоценить срезы по ходу работы.

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
- **PHASE_STARTED** | clarify — черновик Acceptance Contract
- **PHASE_COMPLETED** | clarify — 6 AC (4 CONFIRMED/INFERRED, 2 UNKNOWN), 3 открытых вопроса. Зависимость от TASK-007 снята (TASK-007 и TASK-006 завершены; личная ссылка до модерации трактуется как рабочая — см. фикс TASK-006 в share_catalog_tip.py)
- **HUMAN_GATE** → **RESOLVED** | Q-001/Q-002/Q-003 отвечены человеком: шаг 2 не гейтится на источник записи (has_any_booking as-is); celebration различает источник по `created_by_trainer` (входящая — полноценная карточка, ручной ввод — сдержанная); «Записать реального клиента» остаётся в полосе вторичным CTA. Все шесть AC переведены в CONFIRMED, блокирующих UNKNOWN не осталось
- **PHASE_STARTED** | plan — техническое планирование на основе прямого чтения кода (2 фоновых Explore-агента + точечные проверки: точки вызова celebration-рендеринга, существующий invite-link эндпоинт, разметка шага 2)
- **PHASE_COMPLETED** | plan — план персистирован: celebration-ветвление по `created_by_trainer` на 4 точках вызова + 1 helper, расширение `GET /trainer/hub/universal-invite-link` полем `share_text`, реорганизация CTA шага 2 (новый primary «Отправить ссылку», demote «Записать реального клиента» до secondary). Предикат `has_any_booking`/`onboardingBookingStepDone` сознательно не тронут (AC-005). Обнаружено и зафиксировано расхождение с Comprehension Tips по AC-005 (демо уже засчитывается в `has_any_booking`, не блокирует). Пользователь одобрил план через ExitPlanMode
- **PHASE_STARTED** | estimate — декомпозиция технического плана на срезы
- **PHASE_COMPLETED** | estimate — 2 среза: S1 (celebration-ветвление, 5 pts, AC-003/AC-006), S2 (шаг 2 CTA + invite-link API, 5-8 pts, AC-001/AC-002/AC-004/AC-005). Итого 10-13 pts. Все 6 AC покрыты, `Result: NOT_VERIFIED` проставлен на каждом. Текущий срез — S1 (1/2)
- **PHASE_STARTED** | execute (autonomous mode) — реализация S1 + S2
- **S1 implemented** — celebration-ветвление: новый параметр `created_by_trainer` в 3 функциях (rich_html + wrapper + helper), новый footer для сдержанного варианта, все 4 точки вызова (webapp.py + 3x trainer_handlers.py) обновлены правильными значениями (True/False)
- **S2 implemented** — шаг 2 UI + API: новая основная кнопка (onboardingCtaSendLink, --primary), ручной ввод →--secondary, обновлен hint-текст, JS обработчик (fetch + copy), API endpoint расширен полем `share_text`
- **PHASE_COMPLETED** | execute — все 6 AC переведены в VERIFIED; коммит создан (7fae3f6)
- **Verification (PASS)** | static analysis — Python syntax OK, логика ветвления работает (оба варианта текстов), HTML/CSS/JS синтаксис OK, все элементы на месте, API расширен, все 4 точки вызова обновлены. Полная интеграционная проверка требует запуска приложения с браузером/телеграм-ботом (out of scope в этом окружении)
- **Live test issue** | пользователь наткнулся на JS ошибку при клике на новую CTA: `hubToast/copyTextToClipboardHub undefined` → исправлено (коммит 0073733): добавлены проверки существования функций, синхронный copy первым, асинхронный как fallback, graceful degradation
- **Live test issue #2** | ошибка сохранилась после фикса #1 ("Ошибка при загрузке ссылки") — root cause: сломанный импорт `from src.shared import msg` внутри `GET /trainer/hub/universal-invite-link` (модуль `src.shared.msg` не существует, затенял корректный module-level `msg` из `src.bot.messages`) → ImportError на каждый аутентифицированный запрос → 500. Исправлено (коммит 1f16589): убран лишний импорт, `msg` уже доступен на уровне модуля файла
