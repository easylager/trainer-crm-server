# Parser spec: Гомельский ледовый дворец спорта

- arena_id: 33
- city: Гомель
- parser_key: gomel_hockey_news_v1
- cadence: weekly
- requires_by_egress: false

Не путать с id=34 «Ледовый каток Солнечный» (другой адрес).

## Sources

- schedule+prices: еженедельный пост на https://gomel.hockey.by/news/ с заголовком «Расписание массовых катаний на …»
- пример снимка: https://gomel.hockey.by/news/sobytie/news445332.html (31 авг – 6 сен 2026)
- widget/api: нет стабильного JSON; лента новостей
- job.config JSON (черновик):

```json
{
  "news_index_url": "https://gomel.hockey.by/news/",
  "title_contains": "Расписание массовых катаний",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "weekday_adult_minor": 1000,
  "weekend_adult_minor": 1200,
  "rental_minor": 500,
  "child_price_on_page": false,
  "requires_by_egress": false
}
```

Числа в config — fallback только если абзац прайса совпал по тексту; иначе парсить из поста.

## How to extract (reverse)

1. GET ленту новостей (или search). Взять **самый свежий** материал, чей title содержит «Расписание массовых катаний». Не брать архив, если есть более новый.
2. Kind filter: только строки этого поста. ОХМ/СДЮШОР/матчи — в других материалах, drop.
3. Times: строки вида `N сентября (вторник): 21:15 - 22:00` и несколько интервалов через запятую (`15:00 - 15:45, 20:00 - 20:45`). Год — из даты публикации / текущего. День без сеанса (на снимке среда 2 сен) — не изобретать.
4. Prices в том же абзаце: `пн-чт - 10 рублей, пт-вс - 12 рублей`. Прокат `5 рублей`. **Детской цены нет** → `price_child_minor=null`. Не выдумывать детский тариф.
5. Merge: один слот на интервал. Взр/дет не разделены по строкам.
6. `age_note`: «детям до 10 лет вход после 21:00 запрещен».

## Canonical example (expected after validate)

Пост news445332 (снимок 2026-09-05):

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-04 | 20:00 | 20:45 | public_skate | 1200 | null | 500 |
| 2026-09-05 | 20:00 | 20:45 | public_skate | 1200 | null | 500 |
| 2026-09-06 | 15:00 | 15:45 | public_skate | 1200 | null | 500 |
| 2026-09-06 | 20:00 | 20:45 | public_skate | 1200 | null | 500 |

Полная неделя поста — в `expected.json` (7 слотов). Publisher отфильтрует прошедшее.

## Fixture

`.ai/data/fixtures/gomel-lds/` — `news445332.html` + `expected.json`.

## Blockers / notes

- Каденс weekly: если свежего поста нет — прогон `empty`, старые будущие слоты не затирать.
- Следующая неделя после 6 сен на ленте 2026-09-05 ещё не выложена.
