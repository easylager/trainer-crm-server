# Parser spec: Горки Ледовый дворец

- arena_id: 32
- city: Горки
- parser_key: gorki_home_html_v1
- cadence: weekly
- requires_by_egress: false

Адрес в проде: Вокзальная 23. Сайт ДЮСШ [gorkiled.by](https://gorkiled.by/).

## Sources

- schedule: HTML-блок «МАССОВОЕ КАТАНИЕ» на главной https://gorkiled.by/ (новостная колонка, не `/ru/uslugi`)
- prices: http://gorkiled.by/ru/uslugi — прейскурант «ЛЕДОВОЕ ПОЛЕ»
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://gorkiled.by/",
  "prices_url": "http://gorkiled.by/ru/uslugi",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 45,
  "mk_heading": "МАССОВОЕ КАТАНИЕ",
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET главную. Взять абзацы от «МАССОВОЕ КАТАНИЕ» до следующего чужого блока (конный спорт / объявления / мошенники). Не брать режим работы объекта (8:00–22:00) как слоты МК.
2. Kind: только эти строки → `public_skate`. «ОТМЕНЯЕТСЯ» / турнир → **нет слотов** на указанные дни, не материализовать 20:00.
3. Times: `2-3 СЕНТЯБРЯ: 20.00` → два дня, старт `20:00`. `6 СЕНТЯБРЯ : 17.00` → один день. Нормализовать `H.MM` / `HH.MM` → `HH:MM`. Год из «МАССОВОЕ КАТАНИЕ 2026» / «1 СЕНТЯБРЯ 2026». Строка «возобновляется» без часа — **не** слот.
4. `end = start + 45` с прейскуранта («45 мин»), не угадывать 60.
5. Prices с `/ru/uslugi`, не с главной: взрослый `4 руб. 50 коп.` → 450; дети до 16 `4 руб. 00 коп.` → 400; «Предоставление коньков» `3 руб. 50 коп.` → 350. Drop абонементы 8/12 и аренду поля 220 руб.
6. Merge: один слот на `(local_date, starts_at_local)`.

## Canonical example (expected after validate)

Снимок главной 2026-09-06:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-02 | 20:00 | 20:45 | public_skate | 450 | 400 | 350 |
| 2026-09-03 | 20:00 | 20:45 | public_skate | 450 | 400 | 350 |
| 2026-09-06 | 17:00 | 17:45 | public_skate | 450 | 400 | 350 |

4–5 сентября — отмена, слотов нет. 1 сентября — только анонс возобновления.

## Fixture

`data/fixtures/gorki-lds/` — `mass-skating-home-excerpt.html`, `uslugi.html`, `expected.json` (3 слота).

## Blockers / notes

- Раньше ошибочно skip: смотрели только `/ru/uslugi` (прайс без часов). Сетка на **главной**.
- Каденс weekly: блок переписывают вручную; нет слотов на следующую неделю → прогон `empty`, не крутить 2–6 сен вечно.
