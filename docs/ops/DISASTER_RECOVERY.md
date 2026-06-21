# Disaster recovery (Postgres)

Краткий runbook для Ice Studio / trainer-crm-belarus.

## Что бэкапится

- **Ежедневно:** logical dump Postgres (`pg_dump` SQL, gzip) в off-site bucket — см. [BACKUPS.md](./BACKUPS.md).
- **Не в dump:** файлы S3 (фото, PDF сертификатов) — живут в app bucket; при DR восстанавливаете bucket отдельно или из versioning.

## RTO / RPO (ориентир)

| | Цель |
|---|------|
| **RPO** (сколько данных можно потерять) | ≤ 24 ч (daily backup) |
| **RTO** (сколько времени на поднятие) | 1–3 ч вручную |

## Восстановление из последнего dump

### 1. Скачать backup

```bash
# AWS CLI / rclone / Cloudflare dashboard — скачать последний
# postgres/YYYY/MM/DD/trainer_crm_YYYYMMDD_HHMMSS.sql.gz
gunzip -k trainer_crm_YYYYMMDD_HHMMSS.sql.gz
```

### 2. Целевая база

- Новый Railway Postgres **или** локально:

```bash
docker compose up -d postgres
createdb -h localhost -U trainer_crm trainer_crm_restore
```

### 3. Restore

```bash
psql "postgresql://USER:PASS@HOST:PORT/DBNAME" -v ON_ERROR_STOP=1 -f trainer_crm_YYYYMMDD_HHMMSS.sql
```

Для **пустой** новой БД это обычно достаточно. Если база не пустая — лучше создать **новую** БД и переключить `DATABASE_URL` на неё.

### 4. Миграции

После restore из dump схема уже на момент dump. Проверьте:

```bash
alembic current
alembic upgrade head   # только если dump старше последних миграций
```

### 5. Переключить prod

1. Railway → сервис API → Variables → обновить `DATABASE_URL` / `DATABASE_URL_SYNC`.
2. Redeploy API + bot + notification_service.
3. `GET /health` → `"db": "ok"`.
4. Smoke: логин mini app, одна запись, фото тренера.

## Откат деплоя (без restore БД)

Railway → Deployments → **Redeploy** предыдущего успешного commit.  
Если миграция уже применилась и ломает код — нужен restore dump **до** миграции или down-migration (осторожно, только если писали `downgrade`).

## Проверка бэкапов (раз в месяц)

1. Скачать вчерашний `.sql.gz`.
2. Восстановить в `trainer_crm_test` локально.
3. `pytest tests/ -q --tb=line` или хотя бы `SELECT count(*) FROM bookings;`.

Без пробного restore бэкап не считается рабочим.

## Контакты / эскалация

- Монитор: внешний ping на `/health` (см. BACKUPS.md).
- Ошибки приложения: Sentry (`SENTRY_DSN`).
