# Parser spec: Каток ХК «Юность»

- arena_id: 8
- parser_key: junost_origin_html_v1
- cadence: weekly
- requires_by_egress: true

Прогон **обязан** идти с реального белорусского egress IP. Header-spoof (`X-Forwarded-For`) не работает. Без BY IP origin отвечает **403** — это `ice_scrape_runs.status=blocked`, слоты **не** выдумывать.

## Sources

- schedule: https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/  ← единственный SoT сетки
- prices: та же origin-страница; зеркало https://junost.hockey.by/clubs/skating/ только как подсказка человеку, **не** как fallback времён
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "url": "https://junost.by/seansy_massovogo_kataniya_na_vyhodnyh/",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "requires_by_egress": true,
  "use_fallback_if_schedule_blocked": false,
  "blocked_http_statuses": [403],
  "egress": "by_ip_required"
}
```

## How to extract (reverse)

1. Fetch **только** origin с BY egress (тот же Docker-образ / воркер, но исходящий IP в Беларуси: BY VPS или Railway region BY). Globalping подтверждает 200 с Beltelecom, но публичный API режет тело до 10 КБ — **не** fetch-плоскость продакшена.
2. HTTP 403 / timeout без BY → прогон `blocked`, `sessions=[]`. Запрещено: шаблон «сб/вс 17:00 и 18:15», репринты slivki/hockey.by как расписание.
3. Kind filter: сеансы массового катания на странице → `public_skate`. Drop СДЮШОР, матчи, заточка, прокат «пингвина» как отдельные продукты.
4. Times: парсить фактическую сетку origin (даты + интервалы). Не хардкодить часы. Будни выкладывать только если они есть в HTML.
5. Prices: с origin. Если на origin нет сумм, а сетка есть — слоты с `price_* = null` не публиковать, пока нет трёх (или явно двух + rental null) чисел; зеркало hockey.by на снимке: взр 7.00 / дет до 16 5.50 / прокат 6.00 → 700 / 550 / 600 — можно взять **только** если origin подтвердил те же цифры или не содержит прайса. Не подставлять зеркальные **времена**.
6. Merge: один слот на `(local_date, starts_at_local)`.
7. `age_note` с origin (на зеркале: «детский до 16 лет»).

## Canonical example (expected after validate)

Пока нет полного origin-HTML с BY IP — и публичный Globalping его не даёт — `expected.json` = `sessions: []` + `blocked_without_by_egress: true`. Это терминал V1. После BY VPS: заполнить таблицу с origin, не из репринтов.

## Fixture

`.ai/data/fixtures/minsk-junost/`

| файл | смысл |
|---|---|
| `junost-origin.html` | 403 с не-BY IP |
| `globalping-by-truncated.html` | 200 с BY, обрезано на шапке (~10 КБ) |
| `hockey-skating.html` | зеркало цен, не расписание |
| `expected.json` | терминал V1: пустые слоты, `blocked_without_by_egress` |

## Blockers / notes

- Стабильный парсинг = BY egress на каждый прогон, не «попробовать и откатиться на шаблон».
- Не путать с ledlife.by (другая арена, тот же класс 403).
- INGEST: воркер без BY IP не включает этот job (`is_enabled` можно сеять, скедулер обязан помечать `blocked`).
- Закрыто для V1 без BY VPS. Повторный Globalping 2026-09-06: HTTP 200 Beltelecom, `truncated=true`, 10 КБ шапки — сетки нет. Терминальный SPEC: `sessions=[]`, `blocked_without_by_egress: true`.
