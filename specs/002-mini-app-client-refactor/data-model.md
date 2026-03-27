# Data model (conceptual): 002-mini-app-client-refactor

Персистентные сущности БД **не добавляются**. Ниже — модель **артефактов аудита** и связей для спеки.

## Entities

### ClientScenario

Именованный пользовательский путь: от намерения до результата (например «Запись через каталог → слот → телефон»).

| Field | Description |
|-------|-------------|
| `id` | Стабильный slug: `booking-inline`, `booking-webapp`, `my_requests`, … |
| `steps` | Упорядоченные шаги с точки зрения пользователя (текст) |
| `channels` | `bot` и/или `mini_app` |

### AuditFinding

Одна находка аудита.

| Field | Description |
|-------|-------------|
| `id` | F-001, F-002, … |
| `scenario_id` | Ссылка на `ClientScenario.id` |
| `severity` | `blocker` \| `major` \| `minor` \| `cosmetic` |
| `constitution` | § VII и/или § VIII, если применимо |
| `repro` | Шаги воспроизведения (без PII) |
| `expected_ux` | Ожидаемое поведение после исправления |
| `status` | `open` \| `fixed` \| `wontfix` \| `deferred` |

### BacklogItem

Сводка для приоритизации (может дублировать AuditFinding с `severity`).

| Field | Description |
|-------|-------------|
| `finding_id` | Опциональная ссылка на `AuditFinding.id` |
| `user_impact` | Кратко |
| `order` | Порядок внедрения |

## Relationships

- Один `ClientScenario` — много `AuditFinding`.
- `BacklogItem` может ссылаться на `AuditFinding`.
