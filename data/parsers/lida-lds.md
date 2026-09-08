# Parser spec: Ледовый дворец (Лида)

- arena_id: 37
- city: Лида
- parser_key: lida_html_photo_v1
- cadence: weekly
- requires_by_egress: false

Адрес в проде: Качана 31. Сайт клуба hc-lida.by.

## Sources

- prices + weekly photo: https://hc-lida.by/услуги/массовое-катание
- schedule page (пустая): https://hc-lida.by/осп-сдюшор/расписание-работы-ледовой-арены — заголовок без сетки, **не** SoT
- widget/api: нет; сетка недели — JPG в теле услуги (снимок: Viber `изображение_viber_2026-09-01_…jpg`)
- job.config JSON (черновик):

```json
{
  "prices_url": "https://hc-lida.by/%D1%83%D1%81%D0%BB%D1%83%D0%B3%D0%B8/%D0%BC%D0%B0%D1%81%D1%81%D0%BE%D0%B2%D0%BE%D0%B5-%D0%BA%D0%B0%D1%82%D0%B0%D0%BD%D0%B8%D0%B5",
  "empty_schedule_url": "https://hc-lida.by/%D0%BE%D1%81%D0%BF-%D1%81%D0%B4%D1%8E%D1%88%D0%BE%D1%80/%D1%80%D0%B0%D1%81%D0%BF%D0%B8%D1%81%D0%B0%D0%BD%D0%B8%D0%B5-%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%8B-%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%BE%D0%B9-%D0%B0%D1%80%D0%B5%D0%BD%D1%8B",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 45,
  "adult_minor": 900,
  "child_minor": 700,
  "rental_minor": 600,
  "requires_by_egress": false
}
```

Числа в config — fallback только если абзац прайса совпал; иначе парсить из HTML.

## How to extract (reverse)

1. GET страницу услуги. Цены в тексте. Сетка — `<img>` в `.entry` (не логотип/баннеры). Страница «расписание работы арены» пустая: не считать это `empty` сезона, если на услуге есть свежее фото.
2. Kind: эта страница = МК. Drop аренда льда / матчи (другие URL).
3. Times: с фото недели. Старт `HH:MM`, конца нет → `job.config.default_duration_minutes=45` («Длительность одного сеанса … 45 минут»). Год = год прогона. Сайт обещает обновление **каждый понедельник**.
4. Prices с HTML, **не** с плашки 15/12 на фото (это «посещение с прокатом»):

| | adult | child (до 16) |
|---|---|---|
| лёд без коньков | 9.00 → 900 | 7.00 → 700 |
| прокат | 6.00 → 600 (взр. пара в слот) | 5.00 детский прокат, не отдельная колонка канона |
| combo на фото | 15.00 / 12.00 | не писать одной суммой |

5. Merge: один слот на `(local_date, starts_at_local)`.
6. `age_note`: «детский до 16 лет». Drop заточка, абонемент 12 посещений.

## Canonical example (expected after validate)

Фото недели с 1 сен 2026 (снимок 2026-09-05):

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-05 | 17:00 | 17:45 | public_skate | 900 | 700 | 600 |
| 2026-09-06 | 11:00 | 11:45 | public_skate | 900 | 700 | 600 |
| 2026-09-06 | 20:15 | 21:00 | public_skate | 900 | 700 | 600 |

## Fixture

`data/fixtures/lida-lds/` — `massovoe-katanie.html`, `raspisanije.html`, `week-2026-09-01.jpg` + `expected.json` (10 слотов).

## Blockers / notes

- Geo-блока нет. Каденс weekly (понедельник).
- V1: времена с фикстурного JPG; живой OCR того же URL, когда фото сменится. Не выдумывать сетку с пустой страницы расписания.
