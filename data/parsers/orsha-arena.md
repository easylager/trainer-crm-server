# Parser spec: Орша Ледовая арена

- arena_id: 31
- city: Орша
- parser_key: orsha_ocr_photo_v1
- cadence: weekly
- requires_by_egress: false

Адрес в проде: ул. Владимира Ленина, 79. Сайт клуба lokomotiv-orsha.by. `http://arena-orsha.by/` → 404.

## Sources

- schedule: https://lokomotiv-orsha.by/расписание/ (URL-encode path: `/%D1%80%D0%B0%D1%81%D0%BF%D0%B8%D1%81%D0%B0%D0%BD%D0%B8%D0%B5/`) — WordPress, **JPG**, не HTML-таблица
- prices: https://lokomotiv-orsha.by/прейскурант/ (`/%D0%BF%D1%80%D0%B5%D0%B9%D1%81%D0%BA%D1%83%D1%80%D0%B0%D0%BD%D1%82/`) — HTML-таблица, «действует с 1 января 2026 г.»
- ice photo (неделя 07–13.09.2026, снимок): `https://lokomotiv-orsha.by/wp-content/uploads/2026/09/Ld-07-13.jpg`
- hall photo (не лёд): `Ol-07-13.jpg` / `OL-31-06.jpg` — спорткомплекс «Олимпиец», универсальный зал
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://lokomotiv-orsha.by/%D1%80%D0%B0%D1%81%D0%BF%D0%B8%D1%81%D0%B0%D0%BD%D0%B8%D0%B5/",
  "prices_url": "https://lokomotiv-orsha.by/%D0%BF%D1%80%D0%B5%D0%B9%D1%81%D0%BA%D1%83%D1%80%D0%B0%D0%BD%D1%82/",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "ocr_label": "Массовое катание",
  "image_filename_keep_prefix": "Ld-",
  "image_filename_drop_prefix": ["OL-", "Ol-"],
  "default_duration_minutes": 45,
  "requires_by_egress": false
}
```

Не изобретать CSS-селекторы сетки слотов: сетки в DOM нет. Имена файлов недели меняются (`Ld-31-06.jpg`, `Ld-07-13.jpg`) — брать `<img>` из `.entry-content`, не хардкодить имя.

## How to extract (reverse)

1. GET HTML расписания. В `.entry-content` четыре (или больше) `figure img`. **Keep** файлы с префиксом `Ld-` (ледовая площадка). **Drop** `OL-` / `Ol-` — это зал «Олимпиец» (гандбол / мини-футбол / «время для аренды»), не лёд.
2. Скачать полный JPG (`Ld-*.jpg`, не `-768x` thumb). **OCR** листа. Заголовок фото: «Расписание работы ледовой площадки …». Даты — из шапки колонок (`07.09` … `13.09`), год из шапки («на сентябрь 2026 года»), не rolling week от `run_date`.
3. Kind filter: клетка с текстом **«Массовое катание»** (жёлтый блок) → `public_skate`. Сайт так и называет услугу, не «свободное». Drop: СДЮШОР / ДЮСШ / ВОЦОР, ХК «Локо» / «Локомотив-Орша» / «Юность-Минск» / Дрим-тим / Днепр, шорт-трек, ОПРБ, РС, раскатка, Экстралига, ТО льда.
4. Times: интервал клетки `HH.MM-HH.MM` → `HH:MM`. На снимке 07–13.09 концы **есть** (45 мин). Если OCR дал только старт — `job.config.default_duration_minutes=45` (прейскурант: «45 минут/1 катание»; правила клуба `/10439-2/`). Не угадывать 60.
5. На странице могут висеть **две** недели сразу (31.08–06.09 и 07–13.09 на снимке 2026-09-06). Брать **новейший** `Ld-*`, чья неделя ещё не закончилась или следующая опубликованная. Старый `Ld-*` не смешивать в один батч с новым, если уже выложен следующий.
6. Prices с HTML прейскуранта (парсить, не хардкодить), блок «МАССОВОЕ КАТАНИЕ (без предоставления коньков)»:
   - взрослый `7 руб. 00 коп.` → `price_adult_minor=700`
   - детский (младше 14 лет) `4 руб. 00 коп.` → `price_child_minor=400`
   - прокат: «УСЛУГИ ПРОКАТА» / «Предоставление коньков» `4 руб. 00 коп.` за `1 час/1 человек` → `price_rental_minor=400` (единица часа, сеанс 45 мин — **не** пропорционально урезать)
   - Drop: абонементы 4/8/12 посещений (с коньками и без), «Пингвин», заточка, аренда льда
7. Merge: один слот на `(local_date, starts_at_local)`. Взр/дет не разделены по строкам времени.
8. `session_label`: «Массовое катание». `age_note`: «детский младше 14 лет».

## Canonical example (expected after validate)

Неделя фото Ld-07-13.jpg (3 слота). Снимок 2026-09-06; EXIF Photoshop 2026-09-05 07:57.

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-12 | 21:00 | 21:45 | public_skate | 700 | 400 | 400 |
| 2026-09-13 | 14:45 | 15:30 | public_skate | 700 | 400 | 400 |
| 2026-09-13 | 20:00 | 20:45 | public_skate | 700 | 400 | 400 |

Предыдущая неделя Ld-31-06.jpg (ещё на странице 2026-09-06, не в `expected.json`): сб 05.09 20:45–21:30, вс 06.09 20:00–20:45. Будни МК нет.

## Fixture

`.ai/data/fixtures/orsha-arena/` — `schedule.html`, `prices.html`, `Ld-31-06.jpg`, `OL-31-06.jpg`, `Ld-07-13.jpg`, `Ol-07-13.jpg` + `expected.json` (3 слота недели 07–13).

## Blockers / notes

- Geo-блока нет. Каденс **weekly**: фото меняют раз в неделю (EXIF Ld-07-13: Photoshop 24.6, 2026-09-05).
- Стратегия — OCR (класс DiaMond): искать «Массовое катание» на `Ld-*`. Не HTML-таблицу. `OL-*` не лёд.
- URL картинки нестабилен (`Ld-{dd}-{dd}.jpg`). Брать `img` из `.entry-content`, фильтр по префиксу `Ld-`.
- Если на новой неделе жёлтого «Массовое катание» нет — прогон `empty`.
