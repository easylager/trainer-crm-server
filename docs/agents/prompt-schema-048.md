# Агент SCHEMA — impl TASK-048

Вставь это в **новый** Agent-чат Cursor. Не работай в ветке `feat/TASK-068-*`.

```text
Lane: SCHEMA. Одна задача: TASK-048 (профиль арены). Код писать можно.

Прочитай по порядку:
1. docs/epics/ice-discovery/agent-start.md
2. docs/epics/ice-discovery/agent-git.md
3. docs/epics/ice-discovery/agent-lanes.md (только SCHEMA)
4. .ai/tasks/TASK-048.md целиком

Git:
- Не делай checkout в текущем dirty-дереве пользователя (сейчас может быть feat/TASK-068).
- Если нет worktree — создай соседний: git worktree add -b feat/TASK-048-arena-profile ../trainer-crm-server-wt-task-048 origin/master
  (если нет origin/release/ice-discovery — база origin/master; ветку release/ice-discovery создай от master в этом worktree, PR base = она).
- Работай ТОЛЬКО в этом worktree.
- PR: gh pr create --base release/ice-discovery (не master). Нет train — создай и запушь release/ice-discovery с origin/master, затем PR в неё.

Делай: таблица arena_profiles 1:1 к arenas (slug, район, часы, сезон, amenities, контакты). TDD по AC-001…005. Админка справочника — да. Парсеры, ice_sessions, catalog-main.js, ingestion — нет.

Toolkit (если скилы ai-toolkit-max есть): /research → /plan → /estimate → TDD → тесты. Нет скилов — всё равно TDD по AC.

Не трогай: data/parsers/, прод-БД, webapp.py кроме admin arenas если нужно для AC-003.

Стоп: если для slug/district нужен прод — не пиши в прод; спроси человека.
```
