# Parser spec: ТЦ DiaMond city

- arena_id: 7
- city: Минск
- parser_key: diamond_html_v1
- cadence: weekly
- requires_by_egress: false

## Sources

- schedule: https://diamondcity.by/ledovaya-arena
- prices: https://diamondcity.by/ceny — PNG, не HTML-цифры
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://diamondcity.by/ledovaya-arena",
  "prices_url": "https://diamondcity.by/ceny",
  "price_image_url": "https://diamondcity.by/d/cena_led_2606.png",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "keep_labels": ["МК"],
  "drop_labels": ["ОХМ", "ШРС", "ТОРНАДО", "Тех.обслуживание", "ЗВЕЗДОЧКА", "МИР БЕЗ ГРАНИЦ", "КФК"],
  "disco_marker": "ДИСКОТЕКА",
  "default_duration_minutes": 45,
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET schedule HTML. Сетка — `.blocklist` с `column: 7`: **одна колонка = один день**, заголовок `.blocklist__item_title` (`Пн, 07 сентября` / `Чт,10 сентября` / `Вс,06 сентября` — запятая и пробел нестабильны). **Не** regex по сплошному тексту: соседние дни склеиваются (баг спайка: среда проглатывала четверг).
2. Kind filter: в ячейке `.list__item` оставить только **`МК`** → `public_skate`. Drop `ОХМ` (отработка), `ШРС`, `ТОРНАДО`, `Тех.обслуживание`, `ЗВЕЗДОЧКА` (КФК), `МИР БЕЗ ГРАНИЦ`. Легенда на странице: «МК - массовое катание».
3. Times: `HH:MM-HH:MM` после метки. Нормализовать `15.45` → `15:45`, `17:00--17:45` → `17:00-17:45`, пробелы вокруг `-`. Год не напечатан: `year` = год прогона. Если в одной ячейке `МК` + два интервала (снимок чт 10 сен: `16:45-17:30` и `17:45-18:30`) — **два** слота, второй наследует МК.
4. `МК (ДИСКОТЕКА)` — тот же `public_skate`, `session_label=дискотека` (не отдельный продукт).
5. Prices: на `/ceny` сумм в тексте нет. Официальный прайс — PNG `https://diamondcity.by/d/cena_led_2606.png` (alt «цена лед 26:06», last-modified 2026-06-05). OCR в V1 не обязателен: транскрипция подтверждена по PNG 2026-09-05:

| day_type | adult_minor | child_minor | rental_minor |
|---|---|---|---|
| weekday | 1100 | 800 | 1000 |
| weekend (сб/вс + праздники на PNG) | 1200 | 900 | 1000 |

Сеанс на PNG: **45 минут**. `age_note`: «дети 3–14 лет включительно». Второй PNG `cena_s_10925_kopiya.png` — абонементы / аренда льда / ОХМ 14.00 / ОФК 12.00 — **не** билет МК, drop.
6. Merge: один слот на `(local_date, starts_at_local)`. Взр/дет не разделены по строкам.
7. Прокат защиты / шлем / «пингвин» с PNG в слот не писать.

## Canonical example (expected after validate)

Снимок 2026-09-05, колонки 5–11 сен, 44 слота МК. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor | label |
|---|---|---|---|---|---|---|---|
| 2026-09-05 | 15:00 | 15:45 | public_skate | 1200 | 900 | 1000 | |
| 2026-09-05 | 21:00 | 21:45 | public_skate | 1200 | 900 | 1000 | дискотека |
| 2026-09-07 | 11:45 | 12:30 | public_skate | 1100 | 800 | 1000 | |
| 2026-09-10 | 17:45 | 18:30 | public_skate | 1100 | 800 | 1000 | |

## Fixture

`.ai/data/fixtures/minsk-diamond/` — `ledovaya-arena.html`, `ceny.html` + `expected.json` (44 слота). PNG не кладём: URL в expected.

## Blockers / notes

- Geo-блока нет. Каденс weekly: сетку меняют колонками на неделю.
- Не копировать спайковый `price_minor=800` на все слоты.
- Если PNG сменится (`/d/cena_*.png` другой path) — не хардкодить суммы, пока новый снимок не подтверждён.
