# Parser spec: УСК «Волна» / Ледовая арена ПолесГУ (Пинск)

- arena_id: 24
- city: Пинск
- parser_key: pinsk_polessu_html_v1
- cadence: weekly
- requires_by_egress: false

Домашняя арена «Ястребов» (pinsk.hockey.by) — клубный сайт, МК там нет.

## Sources

- schedule: https://www.polessu.by/ледовая-арена-полесгу
- prices: https://www.polessu.by/спорткомплекс-полесгу-ледовая-арена-0
- widget/api: нет; ЕРИП код 101 = массовое катание, 102 = прокат (суммы на тарифной странице)
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://www.polessu.by/%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0-%D0%BF%D0%BE%D0%BB%D0%B5%D1%81%D0%B3%D1%83",
  "prices_url": "https://www.polessu.by/%D1%81%D0%BF%D0%BE%D1%80%D1%82%D0%BA%D0%BE%D0%BC%D0%BF%D0%BB%D0%B5%D0%BA%D1%81-%D0%BF%D0%BE%D0%BB%D0%B5%D1%81%D0%B3%D1%83-%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0-0",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "requires_by_egress": false
}
```

Страница «Расписание (бассейн, ледовая, тренажёрный зал)» — пустая, не источник.

## How to extract (reverse)

1. GET schedule HTML. Блок после «Расписание массового катания» до «В расписании возможны изменения».
2. Kind filter: только эти интервалы → `public_skate`. Drop аренду поля / любительский хоккей / ОХМ с тарифной страницы (250 / 280 руб).
3. Times: `День DD.MM.YYYY` затем пары `HH.MM – HH.MM` (точка, не двоеточие). Нормализовать в `HH:MM`. Длительность на снимке 45 мин (явные концы). Даты со страницы.
4. Prices с тарифной HTML (не хардкодить):
   - «Массовые катания без предоставления коньков, время катания 45 мин.» `4,40` → 440
   - льготная строка (дошкольники / школьники / студенты дневной при билете) `4,18` → 418
   - «Пользование коньками / 1 пара в час» `4,20` → 420
   - Drop абонементы 4/8 посещений, заточка 4,50
5. Merge: один слот на интервал. Взр/дет не дублируют время.
6. `age_note`: «дошкольники, школьники и студенты дневной формы при предъявлении билета».

## Canonical example (expected after validate)

Снимок 2026-09-06, горизонт 4–13 сен, 18 слотов. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-04 | 21:00 | 21:45 | public_skate | 440 | 418 | 420 |
| 2026-09-06 | 18:30 | 19:15 | public_skate | 440 | 418 | 420 |
| 2026-09-13 | 15:30 | 16:15 | public_skate | 440 | 418 | 420 |

## Fixture

`.ai/data/fixtures/pinsk-volna/` — `schedule.html`, `tariff.html` + `expected.json` (18 слотов).

## Blockers / notes

- Geo-блока нет. Каденс weekly. На 2026-09-06 страница живая (неделя 4–13 сен).
- Если блок расписания пуст — прогон `empty`, старые будущие слоты не затирать.
