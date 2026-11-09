# Parser spec: Арена Ракета — крытый каток в Шушарах

- arena_id: 171
- arena_slug: arena-raketa
- city: Санкт-Петербург/ЛО
- parser_key: raketa_ledokat_v1
- cadence: daily
- requires_by_egress: false

## Sources
- schedule: виджет Ledokat на https://ice-arenaraketa.ru/calender (`div.ledokat-widget-3-schedule[data-id=352fe25daf686bdb4edca223c921acea]`)
- api: `https://api.ledokat.ru/rink-widget/seances/<widget_id>?dateFrom=<пн>&dateTo=<вс>` — одна неделя за запрос; парсер берёт текущую и следующую
- prices: https://ice-arenaraketa.ru/price (Tilda-таблица, «Массовое катание взрослые;60 минут;450 р/час»)
- job.config JSON:

```json
{ "url": "https://ice-arenaraketa.ru/calender", "price_url": "https://ice-arenaraketa.ru/price", "widget_id": "352fe25daf686bdb4edca223c921acea", "rink_id": 1929, "timezone": "Europe/Moscow", "currency_code": "RUB", "default_duration_minutes": 60, "requires_by_egress": false }
```

## How to extract
1. `payload.widget.rinkId` обязан быть 1929 («Арена Ракета»), иначе ошибка прогона: чужой виджет не публикуем.
2. `service == "Массовое катание"` → `public_skate`; `"Час хоккея"` → `hockey_practice`. Аренда, команды (`seanceName` без `service`), «Массовое катание FREE» и всё незнакомое — пропуск.
3. `startedAt`/`finishedAt` — местное время катка; конец не позже начала или через полночь → пропуск. Дубли по `seanceId` схлопываются, `source_id = ledokat:<seanceId>`.
4. `tickets` у катка пустые — цены со страницы /price: взрослый 450, детский (до 16 лет) 400, прокат 350 ₽/час (+залог), час хоккея 550. Страница не ответила или строки нет → цена null, слот остаётся.

## Canonical example (run_date 2026-11-09)
| local_date | start | end | kind | adult_minor |
|---|---|---|---|---|
| 2026-11-09 | 08:15 | 09:15 | hockey_practice | 55000 |
| 2026-11-09 | 13:15 | 14:15 | public_skate | 45000 |

## Fixture
`data/fixtures/spb-arena-raketa/`: `seances-0.json` (неделя 09–15.11.2026, 77 сеансов), `seances-1.json` (следующая неделя ещё пустая), `price.html`; live `curl` 2026-11-09.

## Notes
- «Массовое катание FREE» (3 сеанса в неделю, 12:00) не публикуется: на сайте не сказано, что это значит.
- Студенческий 400, пенсионеры и многодетные 250 ₽ — есть на /price, в карточку, а не в слот.
