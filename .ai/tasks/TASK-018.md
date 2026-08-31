---
task_id: TASK-018
title: Визард знакомства — шаг «Услуги» и кнопка «Далее»
status: IMPLEMENTING
phase: implement
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Привести обязательный визард знакомства (TTV-минимум профиля) к качеству остального тренерского мини-аппа: убрать визуальный разрыв с тёмной темой, полностью переработать шаг «Услуги и цены», и починить «Далее» так, чтобы шаг переключался с **первого** нажатия на **каждом** шаге.

Сейчас это самое слабое место первого опыта: белая форма на тёмном фоне, нечитаемый чёрный блок с чекбоксами услуг (текст «закрашен»), блок «качает» при взаимодействии, а «Далее» стабильно срабатывает только со второго раза.

## Business Context

Визард — первый продуктовый экран после «Обзор» и «Первые шаги». Тренер ещё не увидел ценность CRM; любой friction здесь = отвал до каталога. Шаг услуг — обязательный (3 из 4 в `PROFILE_TT_MINIMAL_WIZARD_ORDER`); если он выглядит сломанным или тормозит, доверие к платформе падает до первой записи.

## Scope

### In Scope

**P1 — Шаг «Услуги и цены» (главная боль)**

- Полный UX/UI redesign блока выбора услуг, тарифов и цен внутри визарда
- Не привязываться к текущей DOM/CSS-реализации: допустимы новая разметка, новые компоненты, упрощённая модель взаимодействия
- Читаемость в тёмной теме ARENA: контраст названий услуг, чекбоксов, кнопки «Тарифы», полей цены
- Стабильная вёрстка без «качания» при раскрытии тарифов, фокусе полей, появлении клавиатуры
- Сохранить бизнес-логику: выбор ≥1 услуги, цены по tier-кодам, описание и «что не входит» — можно упростить подачу, но не потерять данные для API

**P2 — «Далее» только со второго раза (все шаги визарда)**

- Починить переход «Далее» на шагах `anketa_main`, `phone`, `services`, `arenas`
- Регрессия: первый тап всегда либо продвигает шаг, либо показывает понятную ошибку валидации — без «молчаливого» no-op

**P3 — Согласованность визарда с тёмной темой (minor)**

- Визард сейчас намеренно «белый» (`--glide-card` / ICE PAPER внутри `.ob-flow`) на фоне тёмного приложения
- Привести палитру визарда к Arena Depth / `--glide-*` тёмным токенам или сделать адаптивным под `html.trainer-theme-dark`, чтобы не было эффекта «чужого листа поверх приложения»

### Out of Scope

- Полный редизайн всех экранов профиля вне визарда (TASK-017 закрыла общую визуальную трансформацию)
- Админский справочник услуг / tier-кодов
- Шаг «Арены» — функциональный тупик покрывает TASK-010; здесь только визуальная согласованность, если блок затронут общим рефактором визарда
- Логика TTV-гейта и порядок шагов на бэкенде

## Comprehension Tips

### Facts — шаг «Услуги»

- Визард: `#onboardingFlow.ob-flow` в `static/webapp/trainer-profile.html:464-490`; контент переносится в `#obFlowSlot` без дублирования DOM.
- Порядок шагов: `PROFILE_TT_MINIMAL_WIZARD_ORDER = ['anketa_main', 'phone', 'services', 'arenas']` (`trainer-profile-main.js:161`).
- Рендер услуг: `renderServices()` (`trainer-profile-main.js:4136+`) — для каждой услуги из каталога создаётся `.service-row` с checkbox, `.svc-name`, кнопкой `.svc-tier-toggle` («Тарифы ▾»), раскрываемым `.svc-tier-body` (описание, пресеты «что не входит», tier-строки с ценами).
- Базовые стили: `static/webapp/mini-app-trainer-profile.css:355-437` (`.service-row`, checkbox, tier toggle).
- Конфликт тем: блок `.ob-flow` перебивает legacy-крем через `!important` (`mini-app-trainer-profile.css:2823-2886`) — белые `--glide-card` поверхности внутри визарда на тёмном `--glide-bg` приложения.
- В тёмной теме `.service-row` наследует `--tg-theme-bg-color` / тёмные поверхности (`TASK-017` evidence: service-row → `#0B0C0E`), а визард одновременно форсирует `--glide-card` белым — отсюда «закрашенные» нечитаемые названия на скриншоте (тёмный текст/фон или инверсия без контраста).
- «Качание»: визард подстраивает высоту под `visualViewport` (`syncProfileTourBarInset`, `trainer-profile-main.js:1873-1910`) + раскрытие `.svc-tier-body` меняет высоту карточки → layout shift в `#obFlowBody`.

### Facts — «Далее» со второго раза

- Обработчик: `profileBlockTourOnNextClick` → `profileBlockTourOnNextClickBody` (`trainer-profile-main.js:2646-2739`).
- Уже есть workaround: blur активного input + `setTimeout(..., 0)` перед телом (`2646-2672`) — комментарий прямо описывает баг «со второго раза» для шага услуг; позже распространили на все шаги, но **проблема не решена** (репорт пользователя 2026-08-31).
- Дополнительные ветки, где первый клик может «проглотиться»:
  - `dirty` → вызывает `save()` вместо advance (`2705-2718`)
  - `domServicesPricesCoherent()` false на services → early return с toast (`2680-2697`)
  - `setObFlowNextBusy(true)` + async `profileBlockTourFetchBootstrapRefresh()` (`2721+`) — UI busy без явного feedback
  - `is-saving` gate на `#obFlowNext` (`2648-2649`)
- iOS/Telegram WebView: отдельная логика клавиатуры и scroll (`scheduleObFlowFocusedScroll`, `syncProfileTourBarInset`) может перехватывать первый tap.

### Implications

- **Услуги:** патч CSS внутри `.service-row` не спасёт — нужен новый паттерн (например: compact list + bottom sheet для тарифов, или chip-select + inline price pill). Референс — нативные паттерны Telegram/iOS, не текущая «строка-аккордеон».
- **Далее:** нужна диагностика с логированием first-tap path (blur deferred? dirty? coherence? busy?) в WebView; вероятно — синхронный commit значений полей **до** валидации без reliance на blur/setTimeout(0).
- **Тема:** либо убрать белый override в `.ob-flow` для dark, либо сделать визард полностью dark-native — partial white card хуже обоих крайностей.

## Acceptance Criteria

### P1 — Шаг «Услуги»

- [ ] В тёмной теме (`html.trainer-theme-dark`) все названия услуг, чекбоксы и кнопки читаемы без zoom (контраст ≥ WCAG AA для текста)
- [ ] Выбор услуги, раскрытие тарифов и ввод цены не вызывают заметного скачка layout (нет «качания» блока)
- [ ] Новый UI выглядит родным для тренерского мини-аппа (Arena Depth / ribbon-геометрия), а не как legacy-form
- [ ] Сохранение профиля после шага услуг по-прежнему проходит TTV-гейт (`services` в missing_fields = 0)

### P2 — «Далее»

- [ ] На каждом из 4 шагов визарда первое нажатие «Далее» при валидной форме переводит на следующий шаг
- [ ] При невалидной форме первое нажатие показывает ошибку (toast / `#obFlowError` / подсветка поля) — не silent no-op
- [ ] Проверено в Telegram iOS и Android (или симулятор WebView), не только desktop browser

### P3 — Тема визарда

- [ ] В тёмной теме визард не выглядит как белый остров; фон карточки и полей согласован с `--glide-bg` / `--glide-surface`
- [ ] В светлой теме визард остаётся читаемым (реgression ICE PAPER)

## Key Files

| Область | Файлы |
|--------|--------|
| Визард DOM | `static/webapp/trainer-profile.html` (`#onboardingFlow`, `#servicesWrap`) |
| Логика шагов / «Далее» | `static/webapp/trainer-profile-main.js` (`profileBlockTour*`, `renderServices`, `domServicesPricesCoherent`) |
| Стили услуг и визарда | `static/webapp/mini-app-trainer-profile.css` (`.service-row`, `.ob-flow`, `.svc-tier-*`) |
| Токены темы | `static/webapp/theme.css`, `static/webapp/mini-app-trainer-theme.css` |
| TTV-валидация (контракт) | `src/application/trainer_profile_completeness.py` |

## Execution History

- **TASK_CREATED** — по репорту пользователя при прохождении визарда знакомства, шаг «услуги», 2026-08-31
- **IMPLEMENTING** — 2026-08-31:
  - P2: `bindProfileTourBarTap` ловит `pointerup`/`touchend` (без `mousedown preventDefault`); убран автофокус и blur+setTimeout(0) на «Далее».
  - P1: шаг услуг — grouped list, кастомные чекбоксы, тарифы сразу при выборе (adult+child по умолчанию), описание/«не входит» спрятаны в визарде.
  - P3: `html.trainer-theme-dark .ob-flow` использует Arena-токены, а не белую бумагу.
  - Ассеты: `?v=202608312`.
  - Осталось: прогон в Telegram iOS/Android (первый тап «Далее» на всех 4 шагах).
