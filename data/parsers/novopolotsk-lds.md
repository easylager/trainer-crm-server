# Parser spec: Новополоцк Ледовый дворец (ХК «Химик»)

- arena_id: 30
- city: Новополоцк
- parser_key: novopolotsk_himik_html_v1
- cadence: daily
- requires_by_egress: false

Адрес источника: ул. Молодёжная, 94Б — тот же, что prod arena 30.

## Sources

- schedule+prices: https://hchimik.hockey.by/mass-skating/
- widget/api: нет JSON. На странице есть PNG-постер недели — **игнор**, таблица HTML достаточна.
- job.config JSON (черновик):

```json
{
  "url": "https://hchimik.hockey.by/mass-skating/",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "table_selector": "table.schedules-table",
  "date_format": "DD.MM.YYYY",
  "weekday_adult_minor_fallback": 900,
  "weekend_adult_minor_fallback": 1000,
  "rental_minor_fallback": 600,
  "child_price_on_page": false,
  "drop_place_substrings": ["тренировочн"],
  "requires_by_egress": false
}
```

Числа в config — fallback только если абзац прайса совпал по тексту; иначе парсить из «Прейскурант».

## How to extract (reverse)

1. GET страницу. Таблица `.schedules-table`: колонки Дата / Время / Продолжительность / Место. PNG над таблицей не OCR-ить.
2. Kind filter: этот URL — только МК → `public_skate`. Drop пустые строки. Если `Место` содержит «тренировочн» — drop (на снимке все «основная арена»).
3. Times: дата `04.09.2026`, старт `20:00`, длительность `45 минут` → `end = start + 45`. **Битая строка снимка** (06.09.2026 15:00): ячейка «Место» съехала, дата/время/длительность на месте — брать первые три `td` с текстом, не требовать 4 колонки.
4. Prices из «Прейскурант»: будни `9 рублей` → 900; выходные и праздничные `10 рублей` → 1000; прокат `6 рублей` → 600. **Детской цены нет** → `price_child_minor=null`. «Льготный 8 руб» (инвалиды / многодетные / БРСМ) и «сопровождающий 1 руб» — не child, не писать в слот. Заточка 7 руб — drop.
5. Выходной = сб/вс (`weekday() >= 5`); праздники на прайсе есть словами — V1 достаточно сб/вс, если дата не размечена иначе.
6. Merge: один слот на строку таблицы.

## Canonical example (expected after validate)

Снимок 2026-09-06:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-04 | 20:00 | 20:45 | public_skate | 900 | null | 600 |
| 2026-09-05 | 15:00 | 15:45 | public_skate | 1000 | null | 600 |
| 2026-09-05 | 20:00 | 20:45 | public_skate | 1000 | null | 600 |
| 2026-09-06 | 15:00 | 15:45 | public_skate | 1000 | null | 600 |
| 2026-09-06 | 20:00 | 20:45 | public_skate | 1000 | null | 600 |

## Fixture

`data/fixtures/novopolotsk-lds/` — `mass-skating.html` + `expected.json` (5 слотов).

## Blockers / notes

- Geo-блока нет. Таблица короткая (несколько дней) — каденс daily.
- Если таблица пустая при живой странице — `empty`.
