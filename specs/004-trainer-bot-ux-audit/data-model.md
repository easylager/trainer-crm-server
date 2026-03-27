# Data model (conceptual): 004-trainer-bot-ux-audit

Персистентные сущности БД **не добавляются**. Ниже — модель **артефактов аудита** для спеки и плана.

## Entities

### TrainerScenario

Именованный пользовательский путь тренера: от намерения до результата.

| Field | Description |
|-------|-------------|
| `id` | Стабильный slug: `entry_link`, `schedule_editor`, `client_requests`, `my_bookings`, `clients`, `passes_certs`, `subscription`, `stats`, `guide`, … |
| `steps` | Упорядоченные шаги с точки зрения пользователя (короткий текст) |
| `channels` | `bot` и/или `mini_app` |

### AuditFinding

Одна находка аудита.

| Field | Description |
|-------|-------------|
| `id` | F-001, F-002, … |
| `scenario_id` | Ссылка на `TrainerScenario.id` |
| `severity` | `blocker` \| `major` \| `minor` \| `cosmetic` |
| `constitution` | § VII и/или § VIII, если применимо |
| `repro` | Шаги воспроизведения (без PII) |
| `expected_ux` | Ожидаемое поведение после исправления |
| `status` | `open` \| `fixed` \| `wontfix` \| `deferred` |

### BacklogItem

Сводка для приоритизации внедрения.

| Field | Description |
|-------|-------------|
| `finding_id` | Опциональная ссылка на `AuditFinding.id` |
| `user_impact` | Кратко |
| `order` | Порядок внедрения (FR-002) |

## Relationships

- Один `TrainerScenario` — много `AuditFinding`.
- `BacklogItem` может ссылаться на `AuditFinding`.
