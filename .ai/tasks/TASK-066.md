---
task_id: TASK-066
title: Калибровочный набор и метрика точности извлечения
status: IN_PROGRESS
phase: execute
epic: EPIC3
depends_on: [TASK-061]
execution_mode: SUPERVISED
created_at: 2026-09-04
updated_at: 2026-09-06
pr_url: https://github.com/easylager/trainer-crm-server/pull/37
---

# Task

## Objective

Сделать точность извлечения измеримой: эталонный набор расписаний, выверенных человеком, и регулярная сверка с ним каждого прогона конвейера. Эталон и вывод адаптера сравниваются **в каноническом формате `ice_sessions`**, не в HTML виджета.

## Business Context

Без эталона «мы парсим» неотличимо от «мы сломали селектор»: ошибка извлечения выглядит как обычные данные и не падает. Смена адаптера или редизайн сайта могут тихо ухудшить качество. Сверка всегда в каноне `ice_sessions`, не в HTML источника.

## Scope

### In Scope
- Эталон: выверенные человеком слоты в **схеме TASK-050** (вид, время UTC/local, три цены) + сырой снимок на ту же дату. Объём: пилот Минска (~8 МК), не «20–30 любых арен».
- Метрики на прогон: доля верно извлечённых сеансов (полнота), доля выдуманных/лишних (точность), доля верных цен, доля верных типов сеанса — по каждому источнику и суммарно.
- Регрессионный прогон: при изменении адаптера или схемы канона метрики пересчитываются на том же наборе снимков; ухудшение видно до выката.
- Отчёт по метрике в еженедельной сводке здоровья данных (TASK-062).
- Обновление эталона: правило, как и когда добавляются новые арены, чтобы набор не устарел вместе с сайтами.

### Out of Scope
- Сам конвейер — TASK-061.
- Автоматическая публикация без человека — не V1 (старый TASK-067 другой инициативы).

## Acceptance Criteria

### AC-001
Есть эталонный набор по пилотным каткам Минска с МК: сырой снимок источника + выверенное человеком расписание в каноне `ice_sessions` (три цены, kind, UTC) на ту же дату.
Requirement: CONFIRMED
Verification method: наличие набора в репозитории/хранилище + проверка одной записи вручную

### AC-002
Прогон извлечения по эталону выдаёт числовые метрики полноты и точности по сеансам, ценам и типам — суммарно и по каждому источнику.
Requirement: CONFIRMED
Verification method: automated/integration (запуск на эталоне → отчёт с числами)

### AC-003
Изменение адаптера/схемы канона автоматически проверяется на эталоне, и ухудшение метрик видно до выката в прод.
Requirement: CONFIRMED
Verification method: automated (регрессионный тест в CI или отдельная команда с порогом)

### AC-004
Метрика точности попадает в еженедельную сводку здоровья данных.
Requirement: CONFIRMED
Verification method: manual (сводка содержит числа)

## Edge Cases

### EDGE-001
Источник изменился с момента снятия эталона — сверка на устаревшем снимке остаётся корректной (сравниваем извлечение из того же сырья), но эталон нужно обновлять по календарю.
Severity: MEDIUM
Status: ADDRESSED
Rule: `.ai/data/calibration/README.md` (refresh on new human-verified snapshot / expired horizon / quarterly review; never to match a broken adapter).

### EDGE-002
Расписание неоднозначно даже для человека («в выходные с 11:00, уточняйте») — такие случаи должны быть в эталоне помечены отдельно и не портить метрику.
Severity: MEDIUM
Status: ADDRESSED
Sessions with `"ambiguous": true` / `"exclude_from_scoring": true` are kept in gold and dropped from recall/precision/price/kind. Current Minsk fixtures have none; unit test covers the flag.

## Tests
- integration: прогон по эталону, отчёт с метриками (AC-002)
- regression: изменение адаптера → падение метрики видно (AC-003)

## Risks
- Эталон, который никто не обновляет, со временем начинает мерить прошлое. Правило обновления — часть задачи, а не пожелание.

## Execution History
- **TASK_CREATED** (2026-09-04) — EPIC3
- **CANONICAL** (2026-09-05) — сверка в формате ice_sessions; эталон = пилот Минска, не 20–30 любых; без LLM-промпта
- **IN_PROGRESS** (2026-09-06) — PR https://github.com/easylager/trainer-crm-server/pull/37 against `release/ice-discovery`. Gold 7 Minsk MK fixtures; runner + CI floors; TASK-062 hook `metrics_for_digest`. Not merged. DiaMond 7 missed `<div>` MK cells left as TASK-061 follow-up.
