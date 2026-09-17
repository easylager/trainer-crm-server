# Parser spec: Ледовый дворец «Сокольники»

- arena_id: 58
- parser_key: ldsokolniki_html_v1
- cadence: daily
- requires_by_egress: false

## Sources

- schedule: https://ld-sokolniki.ru/massovye-kataniya/ (server-rendered HTML, Bitrix/Intec CMS, никакого JS-виджета)
- prices: та же страница (прокат — плоским текстом, не по сеансам)
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "schedule_url": "https://ld-sokolniki.ru/massovye-kataniya/",
  "timezone": "Europe/Moscow",
  "currency_code": "RUB",
  "kind": "public_skate",
  "session_name": "МК",
  "session_name_meaning": "массовые катания",
  "rental_price_flat_minor": 30000,
  "child_price_available": false,
  "prices_already_minor": true,
  "requires_by_egress": false,
  "requires_auth": false
}
```

## How to extract (reverse)

1. GET `https://ld-sokolniki.ru/massovye-kataniya/` без авторизации, без cookie. Страница отдаётся сразу с готовой разметкой (проверено `curl` без UA-игр и через WebFetch — идентичный контент, geo-блока нет).
2. Игнорировать весь остальной HTML страницы (шапка, меню, футер, HTML-комментарий с галереей `<!--<div class="left-col">...-->`). Единственный нужный узел — `<div class="schedule-list">` внутри `.intec-content-wrapper .right-col`.
3. Для каждого `<div class="schedule-item">`: `.schedule-item__date > span` даёт дату уже в формате `DD.MM.YYYY` (год явно напечатан, в отличие от Чижовки — не нужно гадать год). Парсить как `local_date`.
4. Внутри `.schedule-item-block` каждая строка — `<div class="schedule-item-row">` (первая без обёртки-разделителя, следующие отделены `<hr>`). `.schedule-item__time` — текст вида `19:15-20:15`, сплит по `-` → `starts_at_local`/`ends_at_local` напрямую, дефолтная длительность не нужна (в отличие от Минск-Арены/Чижовки, здесь конец сеанса всегда указан).
5. `.schedule-item__name` — всегда `МК` (сокращение «массовые катания», расшифровано текстом на той же странице). `kind = public_skate`, `session_label = "МК"`.
6. `.schedule-item__price` — текст вида `600 руб.` Строгий regex на число + `руб`. Цена **не** в минорных единицах — умножать на 100 (kopecks) для `price_adult_minor`. `prices_already_minor: false`.
7. Раздельной детской цены на сайте нет (ни на этой странице, ни в остальной навигации — проверено меню сайта). `price_child_minor = null` для всех сессий этого источника.
8. Прокат коньков — не по сеансам, единая строка текстом на странице: «Прокат коньков - 300 руб./сеанс». Применять как **плоскую** `price_rental_minor = 30000` ко всем публичным сеансам этой страницы (не парсить как отдельное событие).
9. Если `.schedule-list` пуст или отсутствуют `.schedule-item` (на странице остаётся только предупреждение «Если в данный момент на сайте не размещено расписание сеансов, значит пока возможности покататься нет.») — это валидное пустое состояние, не ошибка. Горизонт короткий (на снимке — **1 дата, 2 сеанса**), похоже на паттерн Минск-Арены: касса/админ выкладывает ближайший день вручную. Каденс **daily**, чтобы не пропустить новую дату.
10. Merge не нужен: сайт уже кладёт один сеанс = одна строка с одной ценой (нет раздельных взр/дет строк для слияния, в отличие от обеих BY-спек).

## Canonical example (expected after validate)

Снимок 2026-09-17, единственная опубликованная дата на странице:

| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor | label |
|---|---|---|---|---|---|---|---|
| 2026-09-20 | 19:15 | 20:15 | public_skate | 60000 | null | 30000 | МК |
| 2026-09-20 | 20:30 | 21:30 | public_skate | 60000 | null | 30000 | МК |

`currency_code=RUB` (600 руб. и 300 руб./сеанс — рубли, **не** переводить в BYN). Таймзона на странице явно не подписана; сайт и адрес физически в Москве (Europe/Moscow) — так же трактуется и в задаче на этот пилот.

## Fixture

`data/fixtures/msk-sokolniki/` — `massovye-kataniya.html` (полный HTML, снимок 2026-09-17) + `expected.json`.

## Blockers / notes

- Geo-блока нет: страница отдаётся и через обычный `curl` (без VPN/прокси), и через WebFetch — идентичное содержимое.
- HTML — статический серверный рендер (Bitrix/Intec CMS, `intec-content`), Playwright не нужен.
- Раздельной детской цены на сайте нет вообще (проверено меню и саму страницу) — это не баг парсера, а особенность источника.
- Горизонт публикации короткий и, похоже, обновляется вручную администратором зала — если `schedule-list` неделями не меняется, это ожидаемо, а не сигнал поломки парсера.
- Отдельной страницы цен нет — прокат зашит текстом на той же странице расписания.
- Черновик job.config выше финализирован при реализации адаптера (`SokolnikiHtmlParser`): добавлен явный `currency_code: RUB` (в черновике отсутствовал — без него `IceSessionNormalizer` тихо подставил бы `BYN`) и `prices_already_minor` изменён с `false` на `true` — адаптер сам конвертирует цену со страницы в минорные единицы через `parse_price_to_minor` (как остальные HTML-адаптеры этого репозитория), а `rental_price_flat_minor: 30000` уже записан в минорных единицах.
