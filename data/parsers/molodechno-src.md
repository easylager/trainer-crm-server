# Parser spec: СРЦ Молодечно / Олимпик-2011

- arena_id: 18
- arena_slug: molodechno-src
- city: Молодечно
- parser_key: molodechno_src_v1
- cadence: daily
- requires_by_egress: false

Адрес: ул. Великий Гостинец, 102. Официальная страница ледовой арены на `src.by` (раздел `/WDKL/`).

## Sources

- schedule+prices: https://src.by/WDKL/ледовая-арена (канонический URL с percent-encoding кириллицы)
- widget/api: нет
- job.config JSON:

```json
{
  "url": "https://src.by/WDKL/%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 45,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET HTML одной страницы (`source_io.load_source_text`).
2. Блок **«Сеансы массового катания:»** — строки вида `DD.MM. в HH:MM, HH:MM, …` (год не печатают). Год — через `infer_date_from_day_month` + `parser_reference_date` (около 1 января проверять декабрь vs январь).
3. Kind: все эти сеансы = `public_skate` (`kind_raw` «Массовое катание»).
4. Times: на странице только время **начала**; конец = начало + **45 минут** (текст на странице: «Длительность сеанса 45 минут»).
5. Prices — таблица на той же странице, строки **«Сеанс свободного катания»** с единицей **45 минут** (не абонементы):

| | minor |
|---|---|
| взрослые | 8.00 → 800 |
| дети до 14 | 7.00 → 700 |
| прокат | нет суммы в таблице → `null` |

`age_note`: «детский до 14 лет». Не хардкодить цены, если таблица изменится.

6. `schedule_basis`: `live` (расписание текстом на странице на дату прогона).

## Fixture

`data/fixtures/molodechno-src/` — `ledovaya-arena.html` (live-снимок) + `expected.json`.

## Gotchas

- На странице могут оставаться тексты про «остановочный период» — игнорировать, если ниже есть актуальные даты сеансов.
- Несколько таблиц/абонементов с тем же названием услуги — брать только строку на **45 минут**.
