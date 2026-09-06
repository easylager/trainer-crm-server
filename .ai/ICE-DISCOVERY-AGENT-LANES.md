# Ice Discovery — агентные дорожки (параллель)

Карта задач: [`EPIC3-arenas-ice-discovery.md`](./EPIC3-arenas-ice-discovery.md).  
Скилы: **ai-toolkit-max** (`/classify` → `/research` → `/plan` → `/estimate` → `/execute` → `/verify`).  
Toolkit `/verify` ≠ конец. Конец = merge в `release/ice-discovery`.

**Git lock:** PR только в `release/ice-discovery`. **Никогда** `--base master`. Релиз не скоро (владелец 2026-09-06). См. [`ICE-DISCOVERY-AGENT-GIT.md`](./ICE-DISCOVERY-AGENT-GIT.md).

---

## Зачем не один агент на весь эпик

Эпик — четыре независимые оси (A схема, B правда о месте, C клиент, D сбор). Один чат теряет контекст и правит горячие файлы вперемешку. Безопасный параллелизм = **разные файлы + один TASK на ветку + rebase на train перед PR**.

Максимум **3 кодящих агента** одновременно + сколько угодно **SPEC** (только `.ai/parsers/` и фикстуры).

---

## Toolkit на каждую TASK (не пропускать)

Кодящий агент на своей `TASK-NNN`:

1. Прочитать START + GIT + свою TASK целиком.
2. `/classify` — только если в файле нет секции `Strategy`; иначе не плодить второй task file.
3. `/research` → `/plan` → `/estimate` (TDD по AC).
4. `/execute TASK-NNN supervised` (эпик: `execution_mode: SUPERVISED`).
5. `/verify` по AC.
6. PR **base = `release/ice-discovery`**. Status `MERGED` только после merge. **Не** `master`.

SPEC-агент код не пишет: `/research` + спека в `.ai/parsers/`. Цепочка `/execute` ему не нужна, пока нет TASK на код адаптера.

`/next TASK-NNN` — диспетчер **одной** задачи. Не вызывать `/next` без id, если в `.ai/tasks/` много READY — toolkit сам остановится и спросит.

---

## Дорожки

| Lane | Роль | Задачи | Пишет | Не пишет |
|---|---|---|---|---|
| **SPEC** | Реверс катка → спека extract | живые docs | `.ai/parsers/*.md`, `.ai/data/fixtures/<arena>/` | `src/`, миграции, UI |
| **CONTENT** | Досье карточки (не слоты) | 073, 063 | `.ai/data/arena-cards/` | `src/`, парсеры, Google-картинки |
| **SCHEMA** | Канон данных | 048 → 049, 050 | `arena_profiles`, `ice_sessions`, админ, миграции | парсеры, `catalog-main.js` |
| **PLACE** | Правда о месте | 056, 057, 058 | booking / `trainer_arenas` / `trainer_cities` | ingest, карточка арены |
| **INGEST** | Скедулер + адаптеры | 071 → 072 → 065 → 061 → 066 → 062 | `src/ingestion/`, `notification_service`, jobs/runs | клиентский UI |
| **API** | Публичный контракт | 051 | `src/api/routes/public_arenas.py` (новый), use cases | парсеры |
| **UI-card** | Карточка арены vs прототип | 052, **074** | `static/webapp/arena.html`, `arena-card.*` | `ice.html`, `ice-tab.*`, `ice-map.*`, ingest |
| **UI-tab** | Таб «Лёд» + карта vs прототип | 053, 054 ice-tab, **075** | `static/webapp/ice.html`, `ice-tab.*`, `ice-map.*` | `arena.html`, `arena-card.*`, ingest |

074 и 075 **можно параллельно**: файлы не пересекаются. Два агента в `catalog-main.js` запрещены.

---

## Горячие файлы — один писатель

Два агента **не** коммитят в один файл в overlapping PR.

| Файл | Кто |
|---|---|
| `src/infrastructure/db/models.py` | SCHEMA / потом INGEST (новые таблицы — `src/ingestion/`) |
| `src/api/routes/webapp.py` | PLACE |
| `src/api/routes/public.py` | API |
| `static/webapp/catalog-main.js` | **один** UI-агент |
| `static/webapp/arena.html`, `arena-card.js` | только UI-card (074) |
| `static/webapp/ice.html`, `ice-tab.js`, `ice-map.js` | только UI-tab (075) |
| `src/bot/notification_service.py` | только INGEST |
| `.ai/parsers/` | только SPEC |
| `.ai/tasks/TASK-NNN.md` | только агент этой NNN (+ человек) |

Конфликт = стоп, rebase на `release/ice-discovery`, не «оба запушили».

---

## UI: карточка и таб — разные модули

**Лента арены:** строки `ice_sessions` (МК / свободный лёд) — **read-only** (время, цены, «Билет на месте» без `goBooking`). «Записаться» / «Заявка» — **только** слоты тренеров, группы и блок тренеров.

Профиль тренера и онбординг (бывший TASK-054 AC-004/005) — **не** 074/075.

---

## Гигиена git (параллельные сессии)

- Одна TASK = одна ветка `feat/TASK-NNN-…` от свежего train.
- Перед push: `git fetch && rebase origin/release/ice-discovery` (не `--force` на чужое).
- Второй агент = **другой worktree**.
- **Не** merge train → `master`. **Не** PR base `master`.
