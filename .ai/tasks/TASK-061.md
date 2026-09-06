---
task_id: TASK-061
title: Адаптеры МК Минска — стратегия на каток, первый saleframe
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-071, TASK-072, TASK-050]
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-06
city: Минск
design: .ai/DESIGN-INGESTION-PARSERS-V1.md
pr_url: https://github.com/easylager/trainer-crm-server/pull/39
---

# Task

## Objective

Реализовать конкретные стратегии **extract** для минских катков с публичным МК. После extract данные **обязаны** пройти общий transform+validate (TASK-071) и сохраниться **только** как канонические `ice_sessions` — одинаковые поля для saleframe, HTML и ручного ввода. Первый обязательный адаптер — Минск-Арена [saleframe `/service/55`](https://saleframe.minskarena.by/service/55) (слоты на день, каденс daily).

## Business Context

Спайк 2026-09-05 доказал: 4 катка парсятся HTML детерминированно; Минск-Арена живёт в виджете билетов, не на `services.html`. LLM на 150 вёрсток откладывается. Клиенту нужны взр/дет/прокат и актуальные слоты, не ОХМ. Разные сайты — разный extract; **хранение одно** (`DESIGN-INGESTION-PARSERS-V1.md` §3.1).

## Scope

### In Scope
- Стратегии (минимум **три**, лучше по реестру ready):
  1. `minskarena_saleframe_v1` — ABWS JSON service 55 (не CSS виджета). Спека [`.ai/parsers/minsk-minskarena.md`](../parsers/minsk-minskarena.md). Цены API уже minor; прокат **null** (заточка ≠ rental).
  2. `zamok_html_v1` — [`.ai/parsers/minsk-zamok.md`](../parsers/minsk-zamok.md)
  3. `chizhovka_html_v1` — [`.ai/parsers/minsk-chizhovka.md`](../parsers/minsk-chizhovka.md) (led.by — нет спеки SPEC)
- Фильтр kind: только `public_skate` | `open_ice`. ОХМ, школа, аренда льда — drop **до** публикации.
- Merge взр/дет на одно `starts_at` → один канонический слот с `price_adult_minor` + `price_child_minor` (saleframe/55 так устроен на экране).
- После `status=ok`: replace слотов этой арены в горизонте источника **только через publisher** (обычно «сегодня+N дней», для saleframe — день виджета).
- Идемпотентность: тот же набор слотов не плодит дубли.
- Сырой снимок (HTML/JSON) в `raw_ref` прогона, чтобы переразобрать без сети. Переразбор идёт в тот же transform+validate, не в обход.
- Частичный брак: публиковать валидные слоты, в прогоне `slots_dropped`; ≥1 валидный → `ok`.

### Out of Scope
- LLM / OCR DiaMond PNG (цены PNG уже транскрибированы в спайке; OCR — TASK-068 если понадобится).
- ledlife BY-egress как обязательный адаптер (job с `requires_by_egress` можно засидить выключенным).
- Универсальный фреймворк «любой сайт».
- Прямая продажа билетов.

## Acceptance Criteria

### AC-001
Прогон на фикстуре `.ai/data/fixtures/minsk-minskarena/` даёт два слота `public_skate`: 17:00–17:45 и 19:00–19:45, `price_adult_minor=850`, `price_child_minor=600`, `price_rental_minor` null. Не умножать API-цену на 100.
Requirement: CONFIRMED
Verification method: automated/integration на фикстуре + сверка с `expected.json`

### AC-002
Ещё ≥2 минских HTML-адаптера на фикстурах из `.ai/data/` создают корректные слоты МК.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-003
Строки ОХМ/школа/аренда льда не попадают в `ice_sessions`.
Requirement: CONFIRMED
Verification method: automated/unit (фикстура DiaMond/ledlife с миксом)

### AC-004
Повторный прогон с тем же набором слотов не создаёт дублей; `empty` не стирает будущие слоты.
Requirement: CONFIRMED
Verification method: automated/integration

### AC-005
Сборщик пишет слоты только через публикацию после прогона (есть `ice_scrape_runs` id); нет обхода скедулера.
Requirement: CONFIRMED
Verification method: static + integration

### AC-006
Слоты saleframe и HTML-адаптера после публикации имеют **тот же набор колонок** `ice_sessions`; клиентский API не ветвится по `parser_key`. Невалидная цена/время не попадает в таблицу.
Requirement: CONFIRMED
Verification method: automated/integration (сравнить shape двух арен) + unit на validator

## Technical Notes
- Спеки: `.ai/parsers/minsk-*.md`. Фикстуры: `.ai/data/fixtures/minsk-*/`.
- Виджет saleframe — SPA: ходить в `abws.minskarena.by` (calendar + events), не в CSS. Playwright только если API закроют.
- Запуск только из воркера (правило 10 эпика / TASK-071), не из API-процесса.

## Execution History
- **TASK_CREATED** (2026-09-04) — LLM×3 адаптера
- **REFRAMED** (2026-09-05) — детерминированные стратегии; saleframe/55 первый; только МК/свободное
- **CANONICAL** (2026-09-05) — extract ≠ persist; общий transform/validate; один формат `ice_sessions`
- **SPECS_IN** (2026-09-05) — SPEC: saleframe ABWS, 45 мин, цены уже minor, rental null; Замок; Чижовка
- **IN_PROGRESS** (2026-09-06) — extract adapters + publisher; stacked on TASK-065. PR: https://github.com/easylager/trainer-crm-server/pull/35
- **FOLLOW_UP** (2026-09-06) — DiaMond div-wrapped MK cells + dual-interval Thu 10 Sep; gold 44/44, SCORE_FLOORS recall 1.0. PR: https://github.com/easylager/trainer-crm-server/pull/39
