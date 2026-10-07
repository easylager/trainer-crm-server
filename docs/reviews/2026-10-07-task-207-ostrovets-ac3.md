# TASK-207 AC-3: Островец (арена 41) — будние сеансы

**Вывод (парсер прав, сайт не публикует будние сеансы):** расхождение Instagram @ostrovets_arena и
`OstrovetsLdsParser` не баг парсера. Сайт https://sdushor-ostrovets.by/katanie-na-konkah/ в снимках
и на живой странице даёт в основном выходные слоты; Вт/Чт/Пт в HTML часто «нет катаний», тогда как
в Instagram публикуется полная неделя.

**Доказательства:** `data/fixtures/ostrovets-lds/`, `tests/ingestion/test_regional_batch_c_adapters.py`
(`test_ostrovets_lds_skips_no_session_cells`, 10 слотов), разбор в коммите `e01bb8c5`.

**Будние сеансы с сайта / Instagram-sync** — отдельная задача (вне scope TASK-207 phone guard).
Парсер и ingestion в этой ветке не меняем.
