# Parser spec: Брестский ЛДС

- arena_id: 22
- city: Брест
- parser_key: brest_ocr_photo_v1
- cadence: weekly
- requires_by_egress: false

Не путать с id=39 «Озерный / Крытый каток» (дубль адреса, см. `ozerny-rink.md`).

## Sources

- prices: https://brest.hockey.by/raspisanie-svobodnogo-kataniya/
- schedule: https://brest.hockey.by/raspisanie-svobodnogo-kataniya/raspisanie-ledovoy-areny/?clear_cache=Y — **фото**, не HTML-таблица
- photo (снимок недели 31.08–06.09.2026): https://brest.hockey.by/IMG_8523.JPG
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "prices_url": "https://brest.hockey.by/raspisanie-svobodnogo-kataniya/",
  "schedule_url": "https://brest.hockey.by/raspisanie-svobodnogo-kataniya/raspisanie-ledovoy-areny/?clear_cache=Y",
  "timezone": "Europe/Minsk",
  "kind": "open_ice",
  "ocr_label": "СВ кат",
  "image_selector": "img[src*='.JPG'], img[src*='.jpg']",
  "requires_by_egress": false
}
```

Не изобретать CSS-селекторы сетки слотов: сетки в DOM нет.

## How to extract (reverse)

1. GET HTML цен. Strip tags. Блок после «Цены».
2. GET HTML расписания. Найти `<img>` недельного фото (на снимке `src="/IMG_8523.JPG"`). Скачать JPG. **OCR** листа. Искать подпись **«СВ кат»** (свободное катание). Остальные клетки (фигуристы, годы рождения, ХК Брест, любители, КЛХ, профилактика, матчи) — **drop**.
3. Kind filter: только «СВ кат» → `open_ice`. Сайт называет услугу «свободное катание», не «массовое».
4. Times: по OCR, интервал клетки. На фото 01.09.2026 (неделя 31.08–06.09) **каждый день 21:15–22:15** (60 мин). Даты — из шапки фото («с 31 августа по 06 сентября 2026 г.»), не rolling week от `run_date`. Если на новой неделе «СВ кат» нет — прогон `empty`.
5. Prices с HTML (парсить, не хардкодить):
   - «Со своими коньками» взрослый `6.3 рубля` → `price_adult_minor=630`
   - дети до 12 лет `5.3 рубля` → `price_child_minor=530`
   - Drop: абонементы 8 сеансов (32 / 42), «с новыми коньками» 17,90
   - «С арендой коньков» — это **пакет сеанс+прокат** (взр. 13,10 / дет. 11,10), не отдельная строка «прокат пары». Инкременты 6,80 и 5,80 **разные** → в одно поле `price_rental_minor` не класть. На снимке `price_rental_minor=null`.
6. Merge: один слот на `(local_date, starts_at_local)`. Взр/дет не разделены по строкам времени.
7. `session_label`: «СВ кат». `age_note`: «детям до 12 лет».

## Canonical example (expected after validate)

Неделя фото IMG_8523.JPG (7 слотов):

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-08-31 | 21:15 | 22:15 | open_ice | 630 | 530 | null |
| 2026-09-06 | 21:15 | 22:15 | open_ice | 630 | 530 | null |

## Fixture

`data/fixtures/brest-lds/` — `prices.html`, `schedule.html`, `IMG_8523.JPG` + `expected.json` (7 слотов).

## Blockers / notes

- Geo-блока нет. Каденс **weekly**: фото меняют каждую неделю (EXIF снимка: iPhone 14 Pro, 2026-09-01 15:49).
- Стратегия — OCR (класс DiaMond): искать «СВ кат», не HTML-таблицу.
- URL картинки нестабилен (`/IMG_8523.JPG` — имя с камеры). Брать `img` со страницы расписания, не хардкодить имя файла.
