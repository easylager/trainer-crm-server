# Parser spec: Дворец спорта «Могилёв»

- arena_id: 43
- city: Могилев
- parser_key: mogilev_hockey_html_v1
- cadence: daily
- requires_by_egress: false

## Sources

- schedule: https://mogilev.hockey.by/raspisanie/
- prices: https://mogilev.hockey.by/uslugi/?clear_cache=Y (дубль на `/bilety/`)
- widget/api: нет JSON слотов МК. Ссылка «Онлайн продажа» на uslugi — 24guru hockey tickets, не сетка МК.
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://mogilev.hockey.by/raspisanie/",
  "prices_url": "https://mogilev.hockey.by/uslugi/?clear_cache=Y",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "kind_keep_substring": "массовое катание",
  "ice_column_index": 0,
  "label_column_index": -1,
  "drop_label_substrings": ["СДЮШОР", "ХК «", "ХК \"", "технолог", "заливка", "игра п-ва", "сотрудники"],
  "adult_price_marker": "Взрослый билет",
  "child_price_marker": "Детский билет",
  "rental_price_marker": "предоставления коньков",
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET `/raspisanie/`. Одна большая `<table>`: колонка 0 = **Лед**, колонка 1 = ОФП/СФП (игнор), последние колонки = подпись занятия. Заголовки дней — rowspan/colspan строка вида `N сентября 2026 г. (среда)`.
2. **Kind filter (жёстко):** оставить строку **только** если текст подписи содержит `массовое катание` (без учёта регистра). Всё остальное drop: СДЮШОР, ХК «Могилев», «Днепровские львы», игры первенства, технологический перерыв, заливка, «занятие … сотрудники». Не эвристика по вечеру/длительности.
3. Times: интервал из **колонки Льда** (`22.15 – 23.00` / `18.00 – 18.45`). Точка = двоеточие. Не брать время из колонки ОФП той же строки. `end` с страницы, не default. На снимке все МК = 45 мин (совпадает с прайсом «1чел/45 мин»).
4. Prices с `/uslugi/` блок «МАССОВОЕ КАТАНИЕ» / «Цены на предоставляемые услуги во время проведения сеанса»: взрослый `8,00`/`8.00` → 800; детский до 6 лет `5,00` → 500; прокат `7.00` за пару на 45 мин → 700. Не хардкодить. Не брать хоккейные сектора 9/11/13 руб.
5. Merge: один слот на `(local_date, starts_at_local)`. Взр/дет на одном сеансе.
6. `age_note`: «детский до 6 лет».

## Canonical example (expected after validate)

Снимок raspisanie 2026-09-06 (неделя 4–7 сен; 1–3 сен МК нет):

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-04 | 22:15 | 23:00 | public_skate | 800 | 500 | 700 |
| 2026-09-05 | 18:00 | 18:45 | public_skate | 800 | 500 | 700 |
| 2026-09-05 | 20:30 | 21:15 | public_skate | 800 | 500 | 700 |
| 2026-09-06 | 19:15 | 20:00 | public_skate | 800 | 500 | 700 |
| 2026-09-06 | 21:15 | 22:00 | public_skate | 800 | 500 | 700 |
| 2026-09-07 | 21:15 | 22:00 | public_skate | 800 | 500 | 700 |

## Fixture

`.ai/data/fixtures/mogilev-ds/` — `raspisanie.html`, `uslugi.html` + `expected.json` (6 слотов).

## Blockers / notes

- Без kind-фильтра парсер зальёт школу/ХК. Тест адаптера: 0 слотов с «СДЮШОР» в label.
- Geo-блока нет. Каденс daily: сетка на текущую неделю.
- Если МК-строк 0 при живой таблице — прогон `empty`, не error.
