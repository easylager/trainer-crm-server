# Parser spec: Ледовая площадка (Островец)

- arena_id: 41
- city: Островец
- parser_key: ostrovets_html_v1
- cadence: weekly
- requires_by_egress: false

Адрес в проде: Октябрьская 39. Сайт СДЮШОР sdushor-ostrovets.by.

## Sources

- schedule: https://sdushor-ostrovets.by/katanie-na-konkah/
- prices: https://sdushor-ostrovets.by/prejskurant-cen/ ← Перечень № 8 «Платные услуги ледовой площадки» (`dateModified` 2026-08-03)
- related (не лёд): `/ceny-na-uslugi/` = зал бокса, Набережная 13 — **не** источник цен МК
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "url": "https://sdushor-ostrovets.by/katanie-na-konkah/",
  "prices_url": "https://sdushor-ostrovets.by/prejskurant-cen/",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 45,
  "empty_cell": "нет катаний",
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET HTML. Две (и более) `table.cool-table` под «Расписание сеансов массовых катаний». Ячейка заголовка: день недели + «N сентября». Тело: `нет катаний` **или** старты `19.00` / `15.45` по одному на строку `<br>`.
2. Kind: таблицы МК → `public_skate`. Drop тренировки СДЮШОР (другие страницы), июльские подписи к галерее.
3. Times: `19.00` → `19:00`. Конца нет → default **45** (`Продолжительность массового катания 45 минут`). Год = год прогона. Опечатка на снимке: `9 сентяьря`.
4. Drop `нет катаний`. Не материализовать пустые дни.
5. Prices: GET `prejskurant-cen/`, таблица «Перечень № 8». Разовое посещение 45 мин:
   - 1.1 взрослые `6,00` → 600
   - 1.2 дети до 14 лет `4,00` → 400
   - 1.8 предоставление коньков `5,00` / 60 мин → `price_rental_minor=500` (на странице МК коньки выдаются на один сеанс)
   - Drop: абонементы 4/8/безлимит, 1.3 ОХМ, 1.4 инструктор, 1.5–1.7 группы, заточка, билеты, опоры/защита/шлем
   - `/ceny-na-uslugi/` = бокс 10.00 — не брать
6. Merge: один слот на `(local_date, starts_at_local)`.
7. `age_note`: «дети до 14 лет».

## Canonical example (expected after validate)

Снимок 2026-09-05, таблицы 31 авг – 13 сен, 10 слотов. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-04 | 19:00 | 19:45 | public_skate | 600 | 400 | 500 |
| 2026-09-05 | 15:45 | 16:30 | public_skate | 600 | 400 | 500 |
| 2026-09-07 | 20:30 | 21:15 | public_skate | 600 | 400 | 500 |
| 2026-09-13 | 20:00 | 20:45 | public_skate | 600 | 400 | 500 |

## Fixture

`data/fixtures/ostrovets-lds/` — `katanie-na-konkah.html` + `prejskurant-cen.html` + `expected.json`.

## Blockers / notes

- Geo-блока нет. Каденс weekly.
- Новость про ремонт 11 июн – 2 июл 2026 — архив, не текущий блокер.
- Publisher отфильтрует прошедшее (4–5 сен на снимке 6 сен).
- Прейскурант — HTML-таблица, не PDF. Адаптер парсит Перечень № 8, не хардкодит 600/400/500.
