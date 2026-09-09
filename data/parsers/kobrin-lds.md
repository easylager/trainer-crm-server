# Parser spec: Ледовая арена (Кобрин)

- arena_id: 25
- city: Кобрин
- parser_key: kobrin_html_v1
- cadence: weekly
- requires_by_egress: false

ГУ «ДЮСШ по зимним видам спорта г. Кобрина», но **есть публичное МК** (физкультурно-оздоровительное катание) — не skip.

## Sources

- schedule: https://kobrininform.by/afisha/ledovaya-arena/ (таблица «с DD.MM.YY по DD.MM.YY»)
- prices + дубль сетки: https://www.kobrincity.by/katalog/sport-i-fitnes/sportkompleksy/ledovaya-arena-g-kobrina.html
- official `arena.kobrin.edu.by` — timeout на прогоне 2026-09-06, не источник V1
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://kobrininform.by/afisha/ledovaya-arena/",
  "prices_url": "https://www.kobrincity.by/katalog/sport-i-fitnes/sportkompleksy/ledovaya-arena-g-kobrina.html",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "duration_minutes": 45,
  "drop_label_substrings": ["любительский хоккей", "тренажер", "заточка"],
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET kobrininform. Заголовок «Расписание физкультурно-оздоровительного катания c DD.MM.YY по DD.MM.YY». Год: `26` → 2026. Дни недели без календарной даты: пн = start of range.
2. Kind filter: только эта таблица → `public_skate`. **Drop** блок «Любительский хоккей» (12 руб / 90 мин) и школьный набор.
3. Times: старты через `;`. `ends_at_local = start + 45` (явно на странице). Понедельник «—» = нет сеанса.
4. Prices с kobrincity «Стоимость сеансов массового катания» (парсить):
   - без проката от 16 лет `3 руб. 30 коп.` → 330
   - без проката до 16 лет `2 руб. 50 коп.` → 250
   - с прокатом от 16 `7 руб. 60 коп.` / до 16 `6 руб. 25 коп.` — пакеты. Отдельной строки «прокат пары» нет. `price_rental_minor` = взр. пакет − свои: 760−330 = **430**. Детский инкремент 375 — в спеке, в слот не плодить второе поле.
   - Drop: заточка 5,15; скидки 50%; «оплата только за прокат» льготным (суммы нет)
5. Merge: один слот на старт. Взр/дет не режут время.
6. `age_note`: «до 16 лет».

## Canonical example (expected after validate)

Неделя 31.08–06.09.2026, 18 слотов. Примеры:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-01 | 13:00 | 13:45 | public_skate | 330 | 250 | 430 |
| 2026-09-05 | 17:30 | 18:15 | public_skate | 330 | 250 | 430 |
| 2026-09-06 | 12:45 | 13:30 | public_skate | 330 | 250 | 430 |

## Fixture

`.ai/data/fixtures/kobrin-lds/` — `schedule.html`, `prices.html` + `expected.json` (18 слотов).

## Blockers / notes

- Geo-блока нет. Каденс weekly (одна и та же URL, текст недели меняется).
- Сеанс отменяют при <5 посетителей — на extract не влияет.
- kbr.by держит **старую** неделю — не брать, если на kobrininform есть свежее.
