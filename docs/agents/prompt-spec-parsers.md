# Агент SPEC — спеки парсеров Минска (prod READ ONLY)

Вставь это в **второй** Agent-чат Cursor. Код продукта не писать.

```text
Lane: SPEC. Цель: спеки extract для минских катков с массовым/свободным катанием.

Прочитай:
1. docs/epics/ice-discovery/agent-lanes.md (только SPEC)
2. data/parsers/README.md (шаблон)
3. design/ingestion-parsers-v1.md §0 и §3.1 (канон слота)
4. data/minsk-arenas-prod.csv и data/minsk-parser-registry.yaml

Пиши только: data/parsers/minsk-<slug>.md и data/fixtures/minsk-<slug>/
Не пиши: src/, migrations, static/, alembic, pytest.

Прод-БД — ТОЛЬКО ЧТЕНИЕ:
- Список арен: сначала CSV. Обновить можно так:
  railway run -s Postgres-W--1 -- .venv/bin/python scripts/spike/probe_minsk_ice_sources.py --refresh-prod
- Любой свой SQL: сразу после connect выполни
  SET default_transaction_read_only = on;
  SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;
- Разрешено только SELECT. Запрещено: INSERT UPDATE DELETE UPSERT TRUNCATE ALTER DROP COPY FROM alembic pytest против прод URL.
- Если сессия не read-only — СТОП.
- Не коммить секреты (.env, DATABASE_URL).

Порядок катков (МК): Минск Арена id=2 (https://saleframe.minskarena.by/service/55) → Замок id=3 → Чижовка id=6 или led.by id=5. Юность — если успеешь. Не ledlife (403 без BY IP). Не лыжероллер / JUSTSKATE / Финт.

Каждая спека: URL/API в job.config, как отфильтровать только МК/свободное, три цены (взр/дет/прокат), merge взр+дет на одно время в ОДИН канонический слот, фикстура снимка + expected.json.

Ветка (если коммитишь): feat/parser-specs-minsk от release/ice-discovery (или master если train нет). Не checkout ветки SCHEMA. PR base release/ice-discovery. Не трогай models.py.
```
