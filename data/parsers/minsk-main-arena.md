# Parser spec: Минск Арена (главная арена)

- arena_id: 2
- parser_key: minskarena_main_saleframe_v1
- cadence: daily
- requires_by_egress: false

Массовое катание на **большом льду главной арены** (ABWS object «Арена»). Слоты в кассе появляются редко; `calendar` часто пустой — это нормально, не путать с хоккейной площадкой на Конькобежном стадионе (`minskarena_saleframe_v1` / service/55 / arena_id 115).

## Sources

- schedule: https://saleframe.minskarena.by/service/62
- widget/api: `https://abws.minskarena.by`
- job.config: см. `MINSK_MAIN_ARENA_SALEFRAME_CONFIG` в `src/ingestion/seed_config.py` (`service_id` 62, зоны 991/992).

## Fixture

`data/fixtures/minsk-main-arena/` — пока без golden-слотов (календарь пустой на снимках); job включается по реестру, публикация только при живых events.
