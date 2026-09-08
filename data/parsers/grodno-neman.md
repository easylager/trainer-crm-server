# Parser spec: ЛДС Неман (Коммунальная 3а)

- arena_id: 11
- city: Гродно
- parser_key: neman_hockey_news_v1
- cadence: weekly
- requires_by_egress: false

Не путать с id=10 ТЦ «Тринити» (`triniti_ice_api_v1`). Клуб оперирует двумя льдами: ЛДС Коммунальная 3а (`лед Арена`) и ФОК ур. Пышки, 13 (`лед Пышки`). В проде одна запись id=11. МК на снимках — **лёд Пышки** → `session_label`, не отдельная арена и не Тринити.

Бывший ключ `neman_utf16_html_v1` — тот же клуб, виджет `scheduleMK.html`. Оставлять как fallback, **не** публиковать с него апрель.

## Sources

- schedule (live, 2026-09-06): https://neman.hockey.by/news/sobytie/news446875.html — пост «СТАРТ МАССОВЫХ КАТАНИЙ» (опубл. 03 сентября 2026)
- news index: https://neman.hockey.by/news/sobytie/ — брать **самый свежий** материал с «массовых катаний» / «массовое катание» в title
- prices: в том же посте (10 / 7 / 5 руб.)
- widget/api (stale fallback): https://hcneman.by/schedule/scheduleMK.html ← UTF-16 LE + BOM (`FF FE`); футер снимка «обновлено: 26.05.2026 14:40:28»; единственный МК-слот **05 апреля 2026 17:00–18:00**. GET с не-BY IP: HTTP/1.1 + IPv4 (HTTP/2 рвётся). `hcneman.by/news/` и `/schedule/` → 403; `mass-skate.html` и `fok.html` только ссылают на тот же виджет
- **не источник слотов:** https://icepalace.by/schedule/scheduleMK.html → **404** (чужой WP «Новости Бреста»). VK `vk.com/hcneman` (owner `-46632969`) — SPA, в HTML нет МК. Telegram `t.me/s/hcnemangrodno` — на 2026-09-06 постов МК нет. `week.html` / `place4.html` — та же протухшая сетка 30.03–05.04.2026
- job.config JSON (черновик):

```json
{
  "news_index_url": "https://neman.hockey.by/news/sobytie/",
  "title_contains": "массовых катаний",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 60,
  "session_label": "лёд Пышки",
  "widget_url": "https://hcneman.by/schedule/scheduleMK.html",
  "widget_encoding": "utf-16",
  "keep_if_contains": "массовое катание",
  "drop_past_dates": true,
  "stale_if_max_date_lt_run_date": true,
  "requires_by_egress": false
}
```

`default_duration_minutes: 60` — в посте только старты (`17:00 и 18:30`); 60 мин = последний известный интервал виджета (`17:00 - 18:00`). Не угадывать 45. Два старта через 90 мин — при 60 мин не пересекаются.

## How to extract (reverse)

1. GET ленту `/news/sobytie/`. Взять **самый свежий** пост, чей title содержит «массовых катаний» / «массовое катание». Не брать архив, если есть более новый. Снимок: news446875.
2. Kind filter: только тело этого поста. Матчи / заявки / Кубок Салея — другие URL, drop. «ур. Пышки, 13» — адрес ФОК, не третье время (не изобретать слот 13:00).
3. Times: дата `6 сентября` + год публикации поста (2026) → `2026-09-06`. Строка `Время: 17:00 и 18:30` → два старта. `end = start + default_duration_minutes`. Год на дате сеанса может отсутствовать — брать из `<span class="date">` поста.
4. Prices в том же посте: `Стоимость билета -10р.` → `price_adult_minor=1000`; `Для детей (до 12 лет) - 7р.` → `price_child_minor=700`; `Прокат коньков - 5р.` → `price_rental_minor=500`. Не подставлять Тринити.
5. `session_label`: `лёд Пышки`. Merge: один слот на `(local_date, starts_at_local, session_label)`.
6. **Drop past:** `local_date < run_local_date` (Europe/Minsk) — выкинуть. После вечера 6 сен, если нового поста нет → прогон `empty`, старые будущие слоты не затирать.
7. UTF-16 виджет: если max(date) ≥ сегодня — можно взять интервалы с концами оттуда (приоритетнее поста без `end`). Если виджет только в прошлом → **игнор**, не публиковать апрель.

## Canonical example (expected after validate)

Снимок hockey.by news446875, GET 2026-09-06 ~00:30 +03 (слоты ещё сегодня вечером):

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor | session_label |
|---|---|---|---|---|---|---|---|
| 2026-09-06 | 17:00 | 18:00 | public_skate | 1000 | 700 | 500 | лёд Пышки |
| 2026-09-06 | 18:30 | 19:30 | public_skate | 1000 | 700 | 500 | лёд Пышки |

Виджет `scheduleMK.html` на том же прогоне всё ещё 05 апреля 2026 — в `expected.json` не входит.

## Fixture

`data/fixtures/grodno-neman/` — `news446875.html` (live extract) + `scheduleMK.html` (сырой UTF-16, stale evidence) + `expected.json`.

## Blockers / notes

- Виджет **stale** (max_date 2026-04-05, footer 26.05.2026). Не публиковать апрель. Когда обновят — тот же UTF-16 парсер, каденс daily.
- Живой extract = news post. Каденс weekly по ленте; после 6 сен ждать следующий пост, не размножать сетку.
- Geo-блока на hockey.by нет. hcneman виджет: HTTP/1.1 IPv4.
