# Parser spec: Шклов Ледовая арена

- arena_id: 42
- city: Шклов
- parser_key: shklov_ocr_photo_v1
- cadence: weekly
- requires_by_egress: false

Адрес в проде: Почтовая 2. Сайт СДЮШОР [sportshklov.by](http://sportshklov.by/) — **HTTP**. HTTPS падает на TLS (имя сертификата не совпадает) — не считать это «сайта нет».

## Sources

- index: http://sportshklov.by/category/raspisania/
- post snapshot: http://sportshklov.by/2026/09/02/raspisanie-seansov-massovogo-kataniya-31-08-06-09-2026/
- photo: http://sportshklov.by/wp-content/uploads/2026/09/31.08-06.09.2026.jpg
- prices: http://sportshklov.by/uslugi/ (HTML-таблица, не фото)
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "index_url": "http://sportshklov.by/category/raspisania/",
  "prices_url": "http://sportshklov.by/uslugi/",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "title_contains": "массового катания",
  "ocr_header": "РАСПИСАНИЕ СЕАНСОВ МАССОВОГО КАТАНИЯ",
  "fetch_scheme": "http",
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET рубрику `/category/raspisania/` по **http**. Взять свежий пост с «массового катания» в title (дата в permalink). Не брать shklovinfo 2017.
2. В теле поста `<img>` недели (не favicon/баннеры). Скачать JPG. **OCR**. Заголовок фото «РАСПИСАНИЕ СЕАНСОВ МАССОВОГО КАТАНИЯ».
3. Kind: вся сетка на фото = МК → `public_skate`. Хоккей/школа — другие URL, drop.
4. Times: колонка дня `01 сентября (вторник)` + интервалы `13.30-14.15`. Нормализовать точку → `:`. Конец на фото есть — не подставлять 45, если OCR дал оба края. Год из title поста / имени файла.
5. Понедельник 31.08 в шапке недели, на фото снимка колонок нет → слотов нет, не выдумывать.
6. Prices с `/uslugi/`, **не** с фото: взрослый 5,10 → 510; дети до 14 4,20 → 420. Прокат взр. 4,20 / дет. 4,10 — в канон одно поле: `price_rental_minor=420` (взрослый), детский прокат в `age_note`. Drop абонементы и БРСМ 4,90 как adult.
7. Merge: один слот на интервал колонки.

## Canonical example (expected after validate)

Фото `31.08-06.09.2026.jpg` (пост 2 сен 2026). Пн 31.08 на фото нет. Вт–пт по 2 сеанса, сб–вс по 4:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-01 | 13:30 | 14:15 | public_skate | 510 | 420 | 420 |
| 2026-09-05 | 18:00 | 18:45 | public_skate | 510 | 420 | 420 |
| 2026-09-06 | 19:15 | 20:00 | public_skate | 510 | 420 | 420 |

Полная сетка — 16 слотов в `expected.json`.

## Fixture

`.ai/data/fixtures/shklov-arena/` — `raspisania-category.html`, `week-2026-09-02.html`, `31.08-06.09.2026.jpg`, `uslugi.html`, `expected.json`.

## Blockers / notes

- Раньше skip из‑за HTTPS TLS. Источник живой по HTTP, каденс как Брест/Орша: weekly photo.
- Касса 77-871 / охрана 77-803 на фото — не парсить как слоты.
