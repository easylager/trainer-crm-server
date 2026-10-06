# Юность: обновить расписание массовых катаний

Каток «Юность» (arena_id=8) не отдаёт расписание на сайт. Владелец берёт **текст поста**
из Instagram [@junost.by](https://www.instagram.com/junost.by/) и вставляет его в БД через
скрипт `scripts/set_junost_caption.py`.

Скрипт сначала **разбирает текст**, потом показывает таблицу сеансов. Пишет он только
с флагом `--apply`. Если в посте нет даты/времени или все даты уже прошли, он
останавливается и в базу ничего не пишет.

## 1. Взять текст поста

1. Открой пост [@junost.by](https://www.instagram.com/junost.by/) с расписанием на ближайшие выходные.
2. Скопируй **весь текст подписи** (дата, времена, цены).
3. Сохрани в файл, например `~/Desktop/junost-post.txt`.

Пример поста:

```text
11 ОКТЯБРЯ ВОСКРЕСЕНЬЕ
17:00-17:45
18:15-19:00
СТОИМОСТЬ БИЛЕТА:
ВЗРОСЛЫЙ - 8р.
ДЕТСКИЙ - 6р.
УЛ. ПЕРВОМАЙСКАЯ 3,
КРЫТЫЙ КАТОК (ПАРК ИМ. М.ГОРЬКОГО)
```

## 2. Проверить без записи (dry-run)

```bash
cd <папка с репозиторием>
PUB="$(railway run -s Postgres-W--1 -- printenv DATABASE_PUBLIC_URL)"
DB="postgresql://${PUB#postgresql://}"

DATABASE_URL="$DB" DATABASE_URL_SYNC="$DB" PYTHONPATH=. .venv/bin/python \
  scripts/set_junost_caption.py --file ~/Desktop/junost-post.txt
```

В выводе — таблица «дата, начало–конец, цены» и строка `Dry-run — в базу ничего не
записано`. Проверь глазами, что даты и времена совпадают с постом.

## 3. Записать

```bash
DATABASE_URL="$DB" DATABASE_URL_SYNC="$DB" PYTHONPATH=. .venv/bin/python \
  scripts/set_junost_caption.py --file ~/Desktop/junost-post.txt \
  --apply --i-know-this-is-prod
```

Флаг `--i-know-this-is-prod` обязателен для прод-базы. Скрипт одной транзакцией
обновит текст подписи у job id=4 и поставит `next_run_at = now()`, чтобы планировщик
собрал сеансы при следующем тике (обычно в течение минуты).

## 4. Проверить результат (только чтение)

```bash
railway run -s Postgres-W--1 -- psql "$DATABASE_PUBLIC_URL" -c \
  "SELECT local_date, starts_at_local, ends_at_local, price_adult_minor, price_child_minor, status
   FROM ice_sessions WHERE arena_id = 8 ORDER BY starts_at_utc DESC LIMIT 10;"
```

Ожидаемо: строки с датами из поста, `price_adult_minor=800`, `price_child_minor=600`.
Сеансов нет — подожди тик планировщика и повтори запрос.

## Если скрипт ругается

| Сообщение | Что это значит | Что делать |
|---|---|---|
| `Не нашёл ... дату + время сеанса` | Формат поста изменился | Скопировать **весь** текст поста и прислать разработчику |
| `Все сеансы ... уже прошли` | Пост старый | Взять свежий пост на ближайшие выходные |
| `parser_key=... ожидался` / `нет job id=4` | Настроили другой парсер | Прислать текст ошибки разработчику |
| `Текст поста пустой` | Файл пустой или текст не передался | Проверить `--file` |

Скрипт строчку подключения к базе не печатает — URL в вывод не попадает.

## Связанные файлы

- `scripts/set_junost_caption.py` — этот скрипт
- `src/ingestion/junost_instagram_caption.py` — парсер подписи
- `data/parsers/minsk-junost.md` — спека парсера
