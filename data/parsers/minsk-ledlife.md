# Parser spec: СДЮШОР по фигурному катанию (ledlife)

- arena_id: 4
- city: Минск
- parser_key: ledlife_origin_html_v1
- cadence: weekly
- requires_by_egress: true

Прогон **обязан** идти с реального белорусского egress IP. Header-spoof (`X-Forwarded-For`) не работает. Без BY IP origin отвечает **403** — `ice_scrape_runs.status=blocked`, слоты **не** выдумывать. Тот же класс, что Юность (`junost_origin_html_v1`), **другая арена**.

## Sources

- schedule: https://ledlife.by/massovye_kataniya/  ← сетка сеансов
- prices: https://ledlife.by/krytyi_katok434451/ — прейскурант **картинками** (preiskurant3_s_01092026_*.jpg), не HTML-таблица; bands в `mk_price_bands` (с НДС, касса)
- widget/api: нет
- job.config JSON (черновик):

```json
{
  "url": "https://ledlife.by/massovye_kataniya/",
  "prices_url": "https://ledlife.by/stoimost_uslug/",
  "prices_detail_url": "https://ledlife.by/krytyi_katok434451/",
  "mk_price_bands": {
    "day_45": { "adult": 1000, "child": 800 },
    "evening_45": { "adult": 1100, "child": 900 }
  },
  "mk_rental_minor": 700,
  "prices_fallback_urls": [
    "https://ledlife.by/krytyi_ledovyi_katok/",
    "https://ledlife.by/massovoe_katanie/"
  ],
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "requires_by_egress": true,
  "prices_already_minor": false,
  "use_fallback_if_schedule_blocked": false,
  "blocked_http_statuses": [403],
  "egress": "by_ip_required",
  "ohm_price_bands": {"day_60": 1400, "evening_60": 1700}
}
```

## How to extract (reverse)

1. Fetch **только** origin с BY egress. Индексаторы видят HTML-таблицу сеансов; с не-BY IP — nginx/1.10.3 403.
2. HTTP 403 / timeout без BY → прогон `blocked`, `sessions=[]`. Запрещено: шаблон сетки, Wayback, зеркала.
3. Kind filter: строки «МАССОВОЕ КАТАНИЕ» → `public_skate`; «ОТРАБОТКА ХОККЕЙНОГО МАСТЕРСТВА» → `hockey_practice` (цены day 14 / evening 17 BYN за час из `ohm_price_bands` в config, пока прейскурант ОХМ только в индексе). Drop школа `/raspisanie_shkoly/`, группы «Ф-Юниор».
4. Times / prices: парсить фактическую таблицу origin. Не хардкодить.
5. Пока нет полного origin-HTML с BY IP — и публичный Globalping его не даёт — golden = пустые слоты. Это терминал V1.

## Canonical example (expected after validate)

Пока нет полного origin-HTML с BY IP — и публичный Globalping его не даёт — `expected.json` = `sessions: []` + `blocked_without_by_egress: true`. Это терминал V1.

## Fixture

`data/fixtures/minsk-ledlife/`

| файл | смысл |
|---|---|
| `massovye_kataniya-403.html` | 403 с не-BY IP |
| `expected.json` | терминал V1: пустые слоты, `blocked_without_by_egress` |

Усечённый BY-снимок шапки (не сетка): `data/globalping-by-bodies/ledlife.html` — **не** SoT слотов.

## Blockers / notes

- Не включать адаптер как «фейковый парсер» без BY egress.
- Тел. на шапке (+375 17 396-62-74) — не extract.
- INGEST: воркер без BY IP не запускает этот job (`blocked`).
- Закрыто для V1 без BY VPS. Повторный Globalping 2026-09-06: HTTP 200 Beltelecom, `truncated=true`, 10 КБ шапки — сетки нет. Терминальный SPEC: `sessions=[]`, `blocked_without_by_egress: true`.
