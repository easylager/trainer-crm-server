# Parser spec: Витебск Дворец спорта

- arena_id: 29
- city: Витебск
- parser_key: vitebsk_hockey_html_v1
- cadence: daily
- requires_by_egress: false

Не путать с Новополоцком id=30 (ХК «Химик»).

## Sources

- schedule+prices: https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/?clear_cache=Y
- widget/api: онлайн-касса `https://24afisha.by/ru/vitebsk/event/1385106` и оболочка `https://saleframe.24afisha.by/object/124` — как у Минск-Арены Vue пустой; слотов в HTML нет. Re-GET 2026-09-06: 24afisha отдаёт JS interstitial «Verification» (1261 B), JSON-LD в этом прогоне не снять без исполнения JS (не geo-spoof).
- ByCard ABWS: `GET https://abws.bycard.by/api/v3/frame/init?seid=124&target=saleframe&lang=ru` → `calendar=[]` (повтор 2026-09-06 ~00:30). `api/v1/frame/service/124/calendar` и `/events` → 404. Не primary.
- job.config JSON (черновик):

```json
{
  "url": "https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/?clear_cache=Y",
  "afisha_event_url": "https://24afisha.by/ru/vitebsk/event/1385106",
  "saleframe_object_url": "https://saleframe.24afisha.by/object/124",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "default_duration_minutes": 60,
  "weekday_block_labels": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"],
  "adult_price_marker": "Стоимость билета",
  "concession_is_not_child": true,
  "rental_on_page": false,
  "typo_times": { "201:15": "20:15" },
  "requires_by_egress": false
}
```

## How to extract (reverse)

1. GET HTML МК. Взять блок от `<h1>Массовое катание</h1>` / жирного «Массовое катание» до «ПРАВИЛА» / «Онлайн-билеты». Не брать новости в сайдбаре (майские праздники).
2. Kind filter: вся эта страница — массовое катание → `public_skate`. Хоккейные матчи на том же сайте — другие URL, drop.
3. Times: пары абзацев `<b>Четверг</b>` затем `30 апреля - 201:15`. Несколько интервалов через запятую (`14:00, 20:15`). Нормализовать `H:MM` / `HH:MM`. **CMS-опечатка снимка:** `201:15` → `20:15` (карта `typo_times`; общее правило: если час > 23 и строка начинается с `20` — час = 20). Дата: день+месяц из строки (`30 апреля`, `1 мая`) + год, при котором weekday абзаца совпадает с календарём (на снимке 2026). Года на блоке нет. `end = start + 60` из правил п.1.17 «Сеансы … строго по расписанию (60 минут)» — явно в config, не угадывать 45.
4. Prices: `Стоимость билета - 7.00 руб.` → `price_adult_minor=700`. «Многодетным / пенсионерам 6,00» — **не детский**, `price_child_minor=null`. Детского тарифа на странице нет.
5. Rental: пункт 4 правил — прокат ведёт **ИП по договору аренды**, суммы на странице нет → `price_rental_minor=null`. Не брать 5/10 руб. из описания 24afisha (два размера, не одно поле канона).
6. Merge: один слот на `(local_date, starts_at_local)`. Взр/дет не разделены.
7. 24afisha / ByCard: проверить JSON-LD `Event.startDate`/`endDate` как сигнал, что касса жива. **Не** материализовать слоты из диапазона дат без времени. Saleframe HTML пустой Vue. ByCard `calendar=[]` — как у saleframe/55 sibling, не primary.

## Canonical example (expected after validate)

Снимок hockey.by 2026-09-06 ~00:30 +03 (сетка **всё ещё** 30 апр – 3 мая 2026; структуру парсить, арену не drop как empty). `snapshot_stale: true`. Живой продукт **не** публикует эти даты (`drop_past`):

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-04-30 | 20:15 | 21:15 | public_skate | 700 | null | null |
| 2026-05-01 | 14:00 | 15:00 | public_skate | 700 | null | null |
| 2026-05-02 | 20:30 | 21:30 | public_skate | 700 | null | null |
| 2026-05-03 | 20:15 | 21:15 | public_skate | 700 | null | null |

Полный набор — 7 слотов в `expected.json` (extract). Publisher: если после `drop_past` 0 будущих → прогон `empty`, старые будущие слоты не затирать. Не подставлять сеансы из vitbichi.by. Не материализовать 5–6 сен из 24afisha JSON-LD без HH:MM.

## Fixture

`.ai/data/fixtures/vitebsk-ds/` — `massovoe-katanie.html` + `event-jsonld.json` (24afisha Event 5–6 сен, PT60M, 7.00–8.00 BYN, без HH:MM) + `expected.json`.

## Blockers / notes

- HTML-сетка **не обновлена** (re-GET 2026-09-06: те же 30 апр – 3 мая, опечатка `201:15` жива). Extract всё равно. `snapshot_stale: true`. **drop_past; source not refreshed** — не публиковать апр/май как текущее.
- 24afisha/ByCard по-прежнему без HH:MM (init `calendar=[]`, saleframe Vue пустой, HTML кассы — JS wall).
- Geo-блока нет. Каденс daily: ждать, пока клуб обновит weekday-блоки.
- `age_note`: до 3 лет нельзя; 3–12 только с взрослым 18+ на коньках; поздние сеансы — с законным представителем.
