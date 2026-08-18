# Disaster recovery (Postgres + UX)

Краткий runbook для Ice Studio / trainer-crm-belarus.

## Слои защиты (не путать)

| Слой | Что закрывает | Чего не закрывает |
|------|----------------|-------------------|
| **Railway PITR** (bucket на канвасе) | Откат данных на секунду (DROP TABLE, кривая миграция). Restore = **новый** Postgres. | Железо primary: продукт всё равно лежит, пока чинят диск. Живёт **в Railway**. |
| **Volume snapshots** Railway | Быстрый откат того же диска. | Тот же вендор. Сейчас в UI может быть пусто — это отдельно от PITR. |
| **Off-site `pg_dump` → R2** (GitHub Action) | Удалили проект / потеряли volume / Railway недоступен. | Данные после последнего ночного дампа (RPO ≤ 24 ч). |
| **Postgres HA** (Patroni / Neon / Crunchy) | Падение VM primary → failover. | Порчу данных (нужен PITR/dump). |

PITR **не** включают во время hardware failure, пока volume жив — ждать восстановления primary быстрее, чем cutover на restored sibling.

## Поведение продукта, пока БД лежит

API, боты и Mini App **не должны выглядеть пустыми**.

- `GET /health/live` — процесс жив (для **Railway healthcheck**). Если проба останется на `/health`, Railway снимет API с ротации и Mini App не загрузит даже экран техработ.
- `GET /health` и `GET /health/ready` — 503, пока Postgres недоступен или включён `MAINTENANCE_MODE=1`.
- `/api/*` при недоступной БД или флаге → JSON `code=service_unavailable` (503, `Retry-After: 60`).
- Статика `/webapp/*` отдаётся без БД. Mini App показывает «Ведутся технические работы», не пустые списки. Раз в 15 с опрашивает `/health/ready` и сама перезагружается.
- Боты отвечают тем же текстом (не чаще чем раз в 45 с на человека).

Плановые работы: на сервисах API и ботов выставить `MAINTENANCE_MODE=1` (Railway Variables) и задеплоить/рестартнуть. Снять флаг после окна.

## Что бэкапится

- **Ежедневно:** logical dump Postgres (`pg_dump` SQL, gzip) в off-site bucket — см. [BACKUPS.md](./BACKUPS.md). Маркер последнего успешного: `postgres/latest.json`.
- **Не в dump:** файлы S3 (фото, PDF сертификатов) — живут в app bucket; при DR восстанавливаете bucket отдельно или из versioning.

## RTO / RPO (ориентир)

| | Цель |
|---|------|
| **RPO** (сколько данных можно потерять) | ≤ 24 ч (daily backup); секунды — если восстанавливаете из PITR |
| **RTO** (сколько времени на поднятие) | 1–3 ч вручную из dump; PITR sibling — обычно быстрее, если архив жив |

## Восстановление из последнего dump

### 1. Скачать backup

```bash
# AWS CLI / rclone / Cloudflare dashboard — ключ в postgres/latest.json
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

1. Скачать вчерашний `.sql.gz` (или ключ из `latest.json`).
2. Восстановить в `trainer_crm_test` локально.
3. `pytest tests/ -q --tb=line` или хотя бы `SELECT count(*) FROM bookings;`.

Без пробного restore бэкап не считается рабочим.

## Контакты / эскалация

- Монитор: внешний ping на `/health` (готовность) **и** `/health/live` (процесс).
- Railway HTTP healthcheck сервиса API: **`/health/live`**.
- Ошибки приложения: Sentry (`SENTRY_DSN`).
- Ночной dump упал: GitHub Actions + опционально Telegram (`BACKUP_ALERT_*` в [BACKUPS.md](./BACKUPS.md)).
