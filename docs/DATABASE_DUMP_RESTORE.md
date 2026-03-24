# Копирование PostgreSQL: локально → Railway (staging)

Прямой доступ к Railway Postgres с Mac идёт через **публичный** `DATABASE_URL` из dashboard (не `*.railway.internal` — он только внутри сети Railway).

## Какой у вас дамп

Проверка (в репозитории есть скрипт):

```bash
./scripts/analyze_pg_dump.sh path/to/file.dump
```

Или вручную: `pg_restore -l file.dump | head -50`

| Признак в списке TOC | Значение |
|----------------------|----------|
| Строки `TABLE public ...` (без `DATA`) и `SEQUENCE` | **Полный** дамп (схема + данные) |
| Только `TABLE DATA public ...` и `SEQUENCE SET` | **Только данные** (`--data-only`) |

**Файлы в этом репо (проверено):**

- `trainer_crm_local.dump` — **полный** (~431 запись TOC: типы, таблицы, последовательности, данные).
- `trainer_crm_data.dump` — **только данные** (~83 записи: `TABLE DATA` + `setval` для sequences).

Ошибки вида `relation "public.<table>" does not exist` при `COPY` на Railway почти всегда значат: залили **data-only** дамп в БД **без таблиц** (миграции не применялись и полный restore не делали).

## Вариант A — полный дамп (`trainer_crm_local.dump`)

Целевая БД должна быть **пустой** (или вы осознанно делаете `--clean`, что дропнет объекты).

```bash
export DATABASE_URL='postgresql://...'   # публичный URL из Railway

# Опционально: одноразово выровнять search_path
pg_restore -d "$DATABASE_URL" --no-owner --no-acl --clean --if-exists \
  trainer_crm_local.dump
```

Если не нужно дропать существующее — создайте **новую** пустую БД в провайдере или используйте отдельный инстанс. На «голый» Postgres после `CREATE DATABASE` команда выше подходит.

**Замечание:** `alembic_version` в дампе должна быть согласована с кодом; после restore при смене ветки может понадобиться `alembic upgrade head` (или наоборот — не поднимать миграции поверх «чужой» ревизии без понимания).

## Вариант B — только данные (`trainer_crm_data.dump`)

1. Сначала **схема** на целевой БД: деплой API (он выполняет `alembic upgrade head`) **или** вручную с машины, где есть код:

   ```bash
   export DATABASE_URL='postgresql://...'
   alembic upgrade head
   ```

2. Затем данные:

   ```bash
   pg_restore -d "$DATABASE_URL" --no-owner --no-acl --data-only \
     trainer_crm_data.dump
   ```

Если в дампе есть строка для `alembic_version`, она перезапишет версию миграций — убедитесь, что она **не ниже** нужной для кода, или исключите эту таблицу из restore (отдельная тема: `-L` и список из `pg_restore -l`).

## Версия клиента `pg_dump` / `pg_restore`

В заголовке дампа: *Dumped from database version: 16.x*, *Dumped by pg_dump version: 18.x*. Для restore на сервере **PostgreSQL 16** обычно достаточно клиента **16+**; при странных ошибках выровняйте major-версию клиента с сервером.

## Локальный дамп (команды для повторения)

Полный:

```bash
pg_dump -Fc -f trainer_crm_local.dump "$DATABASE_URL"
```

Только данные:

```bash
pg_dump -Fc -a -f trainer_crm_data.dump "$DATABASE_URL"
```

---

*Дампы с прод/стейджа не коммитьте в git — в `.gitignore` добавлены `*.dump`.*
