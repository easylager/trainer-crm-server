# Юность (arena_id=8): расписание из Instagram

Оператор выкладывает массовые катания в [@junost.by](https://www.instagram.com/junost.by/). Сайт `junost.by` не обновляют — **не** используем BY-прокси для Юности.

СДЮШОР (ledlife) по-прежнему: [ice-ingest-by-egress.md](ice-ingest-by-egress.md).

## Каждую неделю (или перед выходными)

1. Скопировать **текст подписи** к посту (дата, времена, цены).

2. Сохранить в файл, например `~/Desktop/junost-post.txt`.

3. Проверка без БД:

   ```bash
   cd /path/to/trainer-crm-server-task111
   PYTHONPATH=. .venv/bin/python scripts/ingest_junost_from_caption.py \
     --file ~/Desktop/junost-post.txt
   ```

   В выводе: `parsed=2 future_slots=2` (или сколько сеансов в посте).

4. Запись в **прод**:

   ```bash
   PUB="$(railway run -s Postgres-W--1 -- printenv DATABASE_PUBLIC_URL)"
   export DATABASE_URL="postgresql+asyncpg://${PUB#postgresql://}"

   PYTHONPATH=. .venv/bin/python scripts/ingest_junost_from_caption.py \
     --file ~/Desktop/junost-post.txt \
     --write-latest \
     --apply \
     --i-know-this-is-prod
   ```

   `--write-latest` обновляет `data/fixtures/minsk-junost/instagram-caption-latest.txt` (можно закоммитить).

5. Проверка API:

   ```bash
   curl -s 'https://api-server-production-dcd9.up.railway.app/api/public/arenas/minsk-junost/sessions' \
     | jq '.sessions[] | {local_date, starts_at_local, price_adult_minor, price_child_minor}'
   ```

## Формат подписи

Парсер понимает типичный пост:

- дата: `Воскресенье | 4 октября`
- время: `17:00 - 17:45` (несколько строк)
- цены: `взрослый - 8 р.`, `детский - 6 р.`, `прокат коньков - 7 р.`

Прошедшие сеансы в прод не попадут (фильтр по `ends_at`).

## После деплоя (один раз)

Переключить job в прод-БД:

```bash
bash scripts/run_ice_ingest_prod_local.sh scripts/seed_ice_parser_jobs.py --apply --i-know-this-is-prod
```

Должно быть: `parser_key=junost_instagram_caption_v1`, `is_enabled=true`.

## Связанные файлы

- `src/ingestion/junost_instagram_caption.py` — парсер
- `scripts/ingest_junost_from_caption.py` — one-shot в прод
- `data/parsers/minsk-junost.md` — спека
