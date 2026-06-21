# Резервные копии Postgres (off-site)

## Где хранить

**Рекомендация: отдельный S3‑совместимый bucket вне Railway** — не смешивать с фото тренеров (`S3_BUCKET`).

| Провайдер | Зачем | Ориентир цены |
|-----------|--------|----------------|
| **Cloudflare R2** | Дёшево, **0 egress** (скачивание бэкапа бесплатно), S3 API | ~$0.015/GB·мес, 10 GB free tier |
| **Backblaze B2** | Самое дешёвое хранение | ~$0.006/GB·мес |
| Railway Storage (второй bucket) | Быстро настроить, **тот же провайдер** что и prod | Удобно, но слабее DR |

Для Ice Studio на ранней стадии типичный сжатый дамп **5–80 MB/день**.  
35 дней × 50 MB ≈ **1.7 GB** → **меньше $0.05/мес** на R2/B2.  
Синк один раз в сутки из GitHub Actions — **копейки**, не «дорогой CDN».

Фото и PDF **не** дублируем в pg_dump: они уже в app bucket; бэкап БД — метаданные + связи. Отдельно при необходимости включите **versioning** на photo bucket.

## Как это работает

1. GitHub Actions [`.github/workflows/backup-postgres.yml`](../../.github/workflows/backup-postgres.yml) — cron 02:15 UTC + ручной запуск.
2. Скрипт [`scripts/ops/backup_postgres.py`](../../scripts/ops/backup_postgres.py):
   - `pg_dump` → gzip
   - upload `s3://<BACKUP_S3_BUCKET>/postgres/YYYY/MM/DD/trainer_crm_*.sql.gz`
   - удаляет объекты старше `BACKUP_RETENTION_DAYS` (по умолчанию 35)

## Настройка (один раз)

### 1. Bucket для бэкапов

**Cloudflare R2 (рекомендуется):**

1. Cloudflare Dashboard → R2 → Create bucket, например `ice-studio-backups`.
2. R2 → Manage R2 API Tokens → Object Read & Write на этот bucket.
3. Endpoint вида `https://<account_id>.r2.cloudflarestorage.com`.

**Backblaze B2:** bucket + Application Key, endpoint `https://s3.<region>.backblazeb2.com`.

### 2. GitHub Secrets (repo → Settings → Secrets → Actions)

| Secret | Пример |
|--------|--------|
| `BACKUP_DATABASE_URL` | `postgresql://user:pass@host.railway.app:5432/railway` — **read-only user желателен** |
| `BACKUP_S3_ENDPOINT` | R2/B2 endpoint URL |
| `BACKUP_S3_ACCESS_KEY` | access key id |
| `BACKUP_S3_SECRET_KEY` | secret |
| `BACKUP_S3_BUCKET` | `ice-studio-backups` |

Опционально (Repository variables):

| Variable | Default |
|----------|---------|
| `BACKUP_S3_REGION` | `auto` |
| `BACKUP_S3_PATH_STYLE` | `true` |
| `BACKUP_RETENTION_DAYS` | `35` |

`BACKUP_DATABASE_URL` возьмите из Railway Postgres → Connect (URL **без** `+asyncpg`).  
Лучше создать отдельного пользователя только с `SELECT` + `pg_dump` (или использовать основной URL, если read-only пока не настроен).

### 3. Проверка

Actions → **Backup Postgres** → **Run workflow**.  
В логе должны быть размер dump и `Uploaded s3://...`.

### 4. Локальный прогон (опционально)

```bash
# В .env задайте BACKUP_* (не коммитьте)
sudo apt-get install postgresql-client   # или brew install libpq
pip install boto3
python scripts/ops/backup_postgres.py
```

## Railway native snapshots

Включите snapshots Postgres в Railway (если на платном плане) **дополнительно** — это быстрый откат внутри платформы. Off-site dump остаётся страховкой «Railway недоступен / volume потерян».

## Восстановление

См. [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md).
