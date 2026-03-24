# Data model — N/A (presentation layer)

Фича не добавляет сущностей БД. Ниже — **инвентарь токенов дизайна** (концептуальная модель для контракта).

| Token (CSS variable) | Semantics | Light default (initial) | Notes |
|---------------------|-----------|-------------------------|-------|
| `--app-bg` | Page background | `#FFFBEB` | Alias/mirror of Telegram bg where applicable |
| `--app-text` | Primary text | `#1a1a1a` | |
| `--app-surface` | Cards, secondary panels | `#FFF3CC` | |
| `--app-muted` | Hints, secondary labels | `#666` | |
| `--app-accent` | Primary CTA | `#F7A600` | |
| `--app-accent-text` | Text on accent | `#1a1a1a` | |
| `--app-danger` | Errors | `#ff3b30` | |
| `--app-radius-sm` / `--app-radius-md` | Corner radii | TBD from pilot audit | Unify duplicated values |
| `--app-font-sans` | Body stack | system-ui, -apple-system, … | One line in theme.css |

Тёмная тема: те же имена, другие значения в медиа-ветке или селекторе темы.

Расширение: `--app-success`, `--app-border` — добавлять при появлении в миграции страниц.
