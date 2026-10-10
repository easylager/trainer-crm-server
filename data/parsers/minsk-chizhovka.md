# Parser spec: Чижовка-арена

- arena_id: 6
- arena_slug: chizhovka
- city: Минск
- parser_key: chizhovka_html_v1
- cadence: weekly
- requires_by_egress: false

## Sources

- schedule (МК): https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah
- schedule (ОХМ): https://chizhovka-arena.by/fizkultura-i-sport/otrabotka-hokkejnogo-masterstva
- prices: https://chizhovka-arena.by/czeny/katanie-na-konkah
- tickets (не extract V1): https://katki.chizhovka-arena.by/
- widget/api: нет; две HTML-страницы
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah",
  "ohm_schedule_url": "https://chizhovka-arena.by/fizkultura-i-sport/otrabotka-hokkejnogo-masterstva",
  "prices_url": "https://chizhovka-arena.by/czeny/katanie-na-konkah",
  "timezone": "Europe/Minsk",
  "default_duration_minutes": 60,
  "kind": "public_skate",
  "keep_rink_labels": ["МА", "БА"],
  "drop_cell_substrings": ["билеты проданы"],
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET schedule HTML. На странице легенда: **БА** = большая арена, **МА** = малая арена. Оба — массовое катание, не взр/дет.
2. Times: **не** regex по сплошному тексту (окно 400 символов склеивает чужие дни — баг спайка, 89 фейковых слотов). Парсить `<table>`: первая строка — день недели + «N месяца»; каждая следующая строка — 7 ячеек. Слот = ячейка `HH.MM МА` или `HH.MM БА` в колонке этой даты.
3. Год не напечатан: `year` = год прогона; около 1 января проверять месяц (декабрь vs январь).
4. Kind filter: ячейки МА/БА на странице МК → `public_skate`, `session_label` = «Малая арена»|«Большая арена». Отдельная страница ОХМ — тот же парсер таблицы, `kind_raw=hockey_practice` → `hockey_practice` (тот же `chizhovka_html_v1`, **второй job не нужен**: один прогон, два URL в config). Drop «билеты проданы». Если БА и МА в одно время — **два** слота.
5. ОХМ prices: строка «ОХМ / 60 мин. / 17» на прайсе → 1700 adult; детской цены нет. `capacity_note`: «до 30 билетов» (со страницы ОХМ).
6. Duration: конца на странице нет. Default **60** явно (`job.config.default_duration_minutes`).
7. Prices МК (вторая страница, uppercased text):
   - `ВЗРОСЛЫЙ БИЛЕТ … 1 ЧАС … 10` → 1000
   - `ДЕТСКИЙ БИЛЕТ ДО 16 ЛЕТ … 1 ЧАС … 7` → 700
   - `ОДНА ПАРА КОНЬКОВ … 1 СЕАНС … 5` → 500
   Drop «билет на трибуны», «прокат ассистента / пингвин» (строку ОХМ на прайсе читаем для ОХМ-слотов).
8. Merge взр+дет: прайс общий на сеанс, не две строки времени. Один слот на `(local_date, starts_at_local, session_label, kind)`.
9. `age_note` МК: «детский до 16 лет»; ОХМ — с страницы отработки (экипировка, дети 4–14 с инструктором).

## Canonical example (expected after validate)

Снимок 2026-09-05, таблица 31 авг – 13 сен, только МА, 19 слотов. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor | label |
|---|---|---|---|---|---|---|---|
| 2026-08-31 | 14:15 | 15:15 | public_skate | 1000 | 700 | 500 | Малая арена |
| 2026-09-05 | 16:30 | 17:30 | public_skate | 1000 | 700 | 500 | Малая арена |
| 2026-09-06 | 19:00 | 20:00 | public_skate | 1000 | 700 | 500 | Малая арена |
| 2026-09-09 | 19:15 | 20:15 | public_skate | 1000 | 700 | 500 | Малая арена |

## Fixture

`data/fixtures/minsk-chizhovka/` — `schedule.html`, `ohm_schedule.html`, `prices.html` + `expected.json` (19 слотов МК).

## Blockers / notes

- Geo-блока нет. Каденс weekly — сетку обновляют таблицей на две недели.
- Не копировать спайковый `price_minor = catalog[0]` (только взрослая).
- Билетный поддомен — отдельный контур, не нужен для extract слотов.
