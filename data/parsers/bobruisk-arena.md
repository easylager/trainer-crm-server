# Parser spec: Бобруйск-арена

- arena_id: 38
- city: Бобруйск
- parser_key: bobruiskarena_html_v1
- cadence: daily
- requires_by_egress: false

## Sources

- schedule: https://bobruiskarena.by/raspisanie
- prices: https://www.bobruiskarena.by/service/sport/massovye-kataniya
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://bobruiskarena.by/raspisanie",
  "prices_url": "https://www.bobruiskarena.by/service/sport/massovye-kataniya",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "schedule_lang_selector": ".post__raspisanie .lang_ru",
  "kind_keep_substring": "массовое катание",
  "drop_label_substrings": ["ДЮСШ", "ДШ", "Тайфун", "игра", "Семейный час", "Раскатка", "Подготовка льда", "Регламент", "ЧПУП", "ЛХК", "МХЛ", "Сахалин", "Амурск"],
  "disco_substring": "дискотека на льду",
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET raspisanie. Парсить **только** `.post__raspisanie .lang_ru` (первый русский столбец). Белорусский `.lang_by` — дубль тех же строк, иначе ×2 слота.
2. Заголовок дня: `Суббота 5 сентября` / `Воскресенье 13 сентября` (год с `resule_date` / даты прогона; на снимке 2026). **Дыра снимка:** после «Пятница 11 сентября» идёт блок без заголовка, затем «Воскресенье 13» — это **суббота 12**. Если после закрытого дня идёт сетка без header — следующий календарный день.
3. **Kind filter (жёстко):** строка содержит `массовое катание` (в `<em>` на снимке) → `public_skate`. Drop ДЮСШ/ДШ/Тайфун/МХЛ/корпоратив (ЧПУП «Сапер-Мебель», ЛХК-Гарнизон), «Семейный час 4+» (другой продукт), раскатка/подготовка льда. Дискотека на льду на прайсе — тот же `public_skate` + `session_label=дискотека`, если так подписана строка расписания (на этом снимке таких строк нет).
4. Times: `19.00-19.45` / `21.15-22.00`. Точка = двоеточие. **Склеенные `<strong>`:** `2` + `1.30-2` + `2.15` → `21.30-22.15` (пн 7 сен, чт 10 сен). Собрать textContent строки до regex `\d{1,2}\.\d{2}\s*-\s*\d{1,2}\.\d{2}`. `end` с страницы.
5. Prices с `/service/sport/massovye-kataniya`: будни `5,50` / 45 мин → 550; выходные `7,00` → 700. Прокат будни `5,40` → 540, выходные `7,50` → 750. **Детской цены нет** → `price_child_minor=null`. Drop абонементы, элитный прокат 9.00, заточка 5.50, бронь 2.00. Выходной = сб/вс.
6. Merge: один слот на `(local_date, starts_at_local)`.

## Canonical example (expected after validate)

Снимок 2026-09-06, 15 слотов МК (без семейного часа). Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-05 | 19:00 | 19:45 | public_skate | 700 | null | 750 |
| 2026-09-07 | 21:30 | 22:15 | public_skate | 550 | null | 540 |
| 2026-09-11 | 21:15 | 22:00 | public_skate | 550 | null | 540 |
| 2026-09-12 | 21:45 | 22:30 | public_skate | 700 | null | 750 |

Вторник 8 сен — МК нет (матч + аренда). Не изобретать.

## Fixture

`.ai/data/fixtures/bobruisk-arena/` — `raspisanie.html`, `massovye-kataniya.html` + `expected.json` (15 слотов).

## Blockers / notes

- Geo-блока нет. Каденс daily.
- Тест: 0 слотов с «ДЮСШ» / «Семейный час» в label; русский столбец не дублировать с `.lang_by`.
