# Parser spec: ТЦ Замок

- arena_id: 3
- parser_key: zamok_html_v1
- cadence: daily
- requires_by_egress: false

## Sources

- schedule: https://tczamok.by/entertainments/ice-rink
- prices: тот же URL (таблица «Цены на посещение»)
- widget/api: нет; обычный HTML
- job.config JSON (черновик):

```json
{
  "url": "https://tczamok.by/entertainments/ice-rink",
  "timezone": "Europe/Minsk",
  "horizon_days": 7,
  "slot_start_suffix": ":15",
  "kind": "public_skate",
  "duration_minutes": 45,
  "price_patterns": {
    "adult_weekday": "Взрослый (В будние дни***) 1 чел/1 сеанс*",
    "adult_weekend": "Взрослый (В выходные и праздничные дни**)",
    "child_weekday": "Детский от 3 до 14 лет (В будние дни***)",
    "child_weekend": "Детский от 3 до 14 лет (В выходные и праздничные дни**)",
    "rental": "Прокат коньков 1 пара/1 сеанс*"
  },
  "drop_label_substrings": ["абонемент", "заточка", "пингвин", "морской котик", "карта посетителя"],
  "prices_already_minor": true,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET HTML страницы катка. Strip tags.
2. Times: пары `HH:MM-HH:MM`. Оставить уникальные старты с суффиксом `:15` (сетка сеансов). На странице сетка в две колонки — после сбора **отсортировать по start**. Конец всегда start+45 (явно на странице: «продолжительность одного сеанса - 45 минут»).
3. Дат на странице нет. Материализовать сетку на `horizon_days` локальных суток от даты прогона (`run_date`). Выходной = `weekday() >= 5` (сб/вс); праздники сайт помечает той же weekend-ценой — V1 достаточно сб/вс.
4. Kind filter: вся эта сетка — массовое катание → `public_skate`. Drop абонементы (8/12/16 сеансов), заточку, прокат «Пингвин»/«Морской котик», карту посетителя. ОХМ/школы на странице нет.
5. Prices (парсить, не хардкодить): после «Цены на посещение Ледового катка»:
   - взрослый будни `10 р.` → 1000
   - взрослый выходные `11 р.` → 1100
   - детский 3–14 будни `8 р.` → 800
   - детский 3–14 выходные `9 р.` → 900
   - прокат коньков `9 р. 00 к.` → 900
6. На слоте три поля: weekday → 1000/800/900, weekend → 1100/900/900. `age_note`: «детский от 3 до 14 лет».
7. Merge: страница не режет взр/дет на разные строки времени. Один слот на `(local_date, starts_at_local)`.

## Canonical example (expected after validate)

`run_date=2026-09-05` (сб). Сетка 13 сеансов/день × 7 дней в `expected.json`. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-05 | 10:15 | 11:00 | public_skate | 1100 | 900 | 900 |
| 2026-09-05 | 17:15 | 18:00 | public_skate | 1100 | 900 | 900 |
| 2026-09-07 | 10:15 | 11:00 | public_skate | 1000 | 800 | 900 |

## Fixture

`.ai/data/fixtures/minsk-zamok/` — `ice-rink.html` + `expected.json` (91 слот при `run_date=2026-09-05`).

## Blockers / notes

- Стабильная HTML-сетка, geo-блока нет.
- Если касса снимет `:15`-фильтр или сменит длительность — чинить спеку, не if в адаптере.
- Спайк захардкодил цены; адаптер обязан читать их с той же страницы.
