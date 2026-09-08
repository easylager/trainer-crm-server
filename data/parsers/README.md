# Parser specs (SPEC lane)

Одна арена — один файл `<city>-<slug>.md`. Это вход для TASK-061, не код.

Канон слота: [`DESIGN-INGESTION-PARSERS-V1.md`](../DESIGN-INGESTION-PARSERS-V1.md) §3.1.  
Дорожки агентов: [`ICE-DISCOVERY-AGENT-LANES.md`](../ICE-DISCOVERY-AGENT-LANES.md).  
Реестр спайка (не спека): [`data/minsk-parser-registry.yaml`](../data/minsk-parser-registry.yaml).

Не писать сюда ОХМ, школу, аренду льда. Только массовое / свободное.

Жёстко (канон [`DESIGN-INGESTION-PARSERS-V1.md`](../DESIGN-INGESTION-PARSERS-V1.md) §6): не выдумывать сетку при 403; `drop_past`; HTTPS TLS fail ≠ сайта нет (пробовать http); Instagram не V1; job без фикстуры не включать.

## Written (SPEC 2026-09-05)

| slug | arena_id | parser_key | cadence | BY egress | fixture |
|---|---|---|---|---|---|
| [minsk-minskarena](./minsk-minskarena.md) | 2 | `minskarena_saleframe_v1` | daily | no | `data/fixtures/minsk-minskarena/` |
| [minsk-zamok](./minsk-zamok.md) | 3 | `zamok_html_v1` | daily | no | `data/fixtures/minsk-zamok/` |
| [minsk-chizhovka](./minsk-chizhovka.md) | 6 | `chizhovka_html_v1` | daily | no | `data/fixtures/minsk-chizhovka/` |
| [minsk-ledby](./minsk-ledby.md) | 5 | `ledby_html_v1` | weekly | no | `data/fixtures/minsk-ledby/` |
| [minsk-junost](./minsk-junost.md) | 8 | `junost_origin_html_v1` | weekly | **yes** | `data/fixtures/minsk-junost/` |
| [grodno-triniti](./grodno-triniti.md) | 10 | `triniti_ice_api_v1` | daily | no | `data/fixtures/grodno-triniti/` |
| [gomel-lds](./gomel-lds.md) | 33 | `gomel_hockey_news_v1` | weekly | no | `data/fixtures/gomel-lds/` |

### SPEC 2026-09-06 (DiaMond / Неман / ledlife + probe)

| slug | arena_id | parser_key | cadence | BY egress | fixture |
|---|---|---|---|---|---|
| [minsk-diamond](./minsk-diamond.md) | 7 | `diamond_html_v1` | weekly | no | `data/fixtures/minsk-diamond/` |
| [grodno-neman](./grodno-neman.md) | 11 | `neman_hockey_news_v1` | weekly | no | `data/fixtures/grodno-neman/` (news 6 сен; виджет stale) |
| [minsk-ledlife](./minsk-ledlife.md) | 4 | `ledlife_origin_html_v1` | weekly | **yes** | `data/fixtures/minsk-ledlife/` (403) |
| [minsk-speed-oval](./minsk-speed-oval.md) | 115 | `minskarena_speed_oval_v1` | daily | no | `data/fixtures/minsk-speed-oval/` (ABWS 139+138) |
| [lida-lds](./lida-lds.md) | 37 | `lida_html_photo_v1` | weekly | no | `data/fixtures/lida-lds/` |
| [soligorsk-szk](./soligorsk-szk.md) | 19 | `soligorsk_szk_html_v1` | weekly | no | `data/fixtures/soligorsk-szk/` |
| [ostrovets-lds](./ostrovets-lds.md) | 41 | `ostrovets_html_v1` | weekly | no | `data/fixtures/ostrovets-lds/` |

### SPEC 2026-09-06 (Brest oblast)

| slug | arena_id | parser_key | cadence | BY egress | fixture |
|---|---|---|---|---|---|
| [brest-lds](./brest-lds.md) | 22 | OCR photo «СВ кат» | weekly | no | `data/fixtures/brest-lds/` |
| [baranovichi-lds](./baranovichi-lds.md) | 23 | HTML week + PDF prices | weekly | no | `data/fixtures/baranovichi-lds/` |
| [pinsk-volna](./pinsk-volna.md) | 24 | HTML week PolessGU | weekly | no | `data/fixtures/pinsk-volna/` |
| [kobrin-lds](./kobrin-lds.md) | 25 | HTML week + HTML prices | weekly | no | `data/fixtures/kobrin-lds/` |

Skip: [bereza-lds](./bereza-lds.md) (26 phone), [pruzhany-sdyushor](./pruzhany-sdyushor.md) (27), [ivatsevichi-lds](./ivatsevichi-lds.md) (28), [ozerny-rink](./ozerny-rink.md) (39 duplicate of 22).

Skip stubs (empty sessions): [molodechno-src](./molodechno-src.md) (18), [zhodino-sdyushor](./zhodino-sdyushor.md) (20), [raubichi-rcop](./raubichi-rcop.md) (15), [silichi-rgc](./silichi-rgc.md) (16), [luninets-olimp](./luninets-olimp.md) (40).

Already skipped Минск (не писать длинные спеки): 9 Олимпик, 12 лыжероллер, 13 JUSTSKATE, 14 Финт.

Adapters (TASK-061) are not implemented here.

## Шаблон файла

```markdown
# Parser spec: <Arena name>

- arena_id: <prod id>
- parser_key: <snake>_v1
- cadence: daily | weekly
- requires_by_egress: false

## Sources
- schedule: <url>
- prices: <url or same>
- widget/api: <url, method, example path>
- job.config JSON (черновик):

\`\`\`json
{ "url": "", "service_id": null }
\`\`\`

## How to extract (reverse)
1. …
2. Kind filter: какие строки/поля = public_skate / open_ice; что drop.
3. Times: …
4. Prices: adult / child / rental — где на странице; как в minor.
5. Merge: взрослый+детский на одно локальное время → один слот.

## Canonical example (expected after validate)
| local_date | starts_at_local | ends_at_local | kind | adult_minor | child_minor | rental_minor |
|---|---|---|---|---|---|---|
| 2026-09-06 | 17:00 | 18:00 | public_skate | 850 | 600 | null |

## Fixture
`data/fixtures/minsk-<slug>/` — сырой HTML/JSON снимка + `expected.json` канона.

## Blockers / notes
-
```
