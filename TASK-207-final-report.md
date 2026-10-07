# TASK-207: Финальный отчёт

## Выполнено

### AC-3: Островец (арена 41) — причина расхождения

**Расследование парсера:**
- Проверен живой сайт https://sdushor-ostrovets.by/katanie-na-konkah/ (07.10.2026)
- Проанализированы фикстуры `data/fixtures/ostrovets-lds/`
- Изучен код парсера `src/ingestion/adapters_regional_batch_c.py:641-715`

**Вывод:** Парсер работает корректно. Расхождение между Instagram и нашими данными вызвано тем, что **сайт не публикует будние сеансы** (Вт/Чт/Пт), которые есть в Instagram.

**Доказательства:**
- Живой сайт (07.10.2026): Пн 20:30, Вт/Ср/Чт/Пт «нет катаний», Сб/Вс — сеансы есть
- Фикстура (05.09.2026): аналогично — будни пустые, выходные заполнены
- Парсер извлекает все данные из HTML — логика не теряет сеансы
- Instagram публикует полное расписание, сайт — урезанное

**Причина:** Instagram ведется активнее, сайт обновляется реже или намеренно показывает только выходные. Это не баг парсера, а расхождение источников данных.

**Рекомендация:** Парсер оставлен без изменений. Если нужны будние сеансы — либо владелец обновляет сайт, либо парсинг Instagram (требует авторизации).

Детали: `TASK-207-ostrovets-findings.md`

### AC-2: Телефоны без цифр не публикуются

**Проблема:** На проде было значение `arena_profiles.phone = "unknown (только email/соцсети)"`, которое рендерилось как пустая ссылка `<a href="tel:">`.

**Решение:**
1. Создана функция `_has_valid_phone_digits(phone: str) -> bool` — проверяет наличие минимум 7 цифр
2. Обновлены все места вывода телефона:
   - `src/application/place_page.py`: `_contacts_html`, `_schedule_mode_call_html`, `_schedule_html` (3 места)
   - `src/application/arena_public_use_cases.py`: `_sanitize_phone()` в `get_public_arena_card()`
   - `src/application/ice_city_day_page.py`: `_unconfirmed_html()`
   - `src/application/selection_page.py`: `_phone_link()`

**Поведение:**
- Телефон без ≥7 цифр: не попадает в SSR-HTML, публичный API возвращает `null`
- Режим `schedule_mode=phone` без валидного телефона: показывается только текст «Телефон уточняем», без кнопки «Позвонить»
- Валидные телефоны (+375291234567, 8-029-123-45-67, etc.) работают как прежде

**Тесты:** `tests/api/test_arena_schedule_mode.py:test_invalid_phone_not_shown_in_ssr_and_api`
- Проверяет SSR (place_page, contacts, schedule)
- Проверяет публичный API (`/api/public/ice/arenas/{id}`)
- Покрывает 3 сценария: невалидный телефон, короткий телефон, валидный телефон

## Изменённые файлы

1. `src/application/place_page.py` (+11 строк)
2. `src/application/arena_public_use_cases.py` (+16 строк)
3. `src/application/ice_city_day_page.py` (+10 строк)
4. `src/application/selection_page.py` (+8 строк)
5. `tests/api/test_arena_schedule_mode.py` (+76 строк)
6. `TASK-207-ostrovets-findings.md` (новый файл, 67 строк)

Всего: 5 файлов изменено, 1 файл добавлен, 188 строк изменений.

## Коммиты

```
931c90a Fix: Add _has_valid_phone_digits to ice_city_day_page.py
e01bb8c TASK-207 AC-3: Document Ostrovets parser investigation
4f294cc TASK-207: Guard invalid phones (< 7 digits) from SSR and public API
```

Ветка: `fix/TASK-207-ostrovets-phone-guard-f627`
Push: успешно (origin/fix/TASK-207-ostrovets-phone-guard-f627)

## Статус тестирования

**Статический анализ (ruff):** ✅ PASS
- Проверены все измененные файлы
- Нарушений не найдено
- `python3 -m ruff check --no-cache` — All checks passed!

**Полные тесты (pytest, node):** ⚠️ НЕ ЗАПУЩЕНЫ
- **Причина:** Cloud Agent среда не имеет настроенного PostgreSQL
- Docker недоступен (`docker: command not found`)
- `psql`, `createdb` недоступны
- `pytest` не установлен изначально

**Ручная проверка синтаксиса:** ✅ PASS
- `python3 -c "import ast; ast.parse(...)` — Syntax OK для всех файлов
- Код компилируется без ошибок

## Что не сделано

1. **Полный прогон pytest** — требуется настройка PostgreSQL и установка зависимостей
2. **Node тесты** (`TZ=UTC node --test tests/js/*.test.js`) — не запускались (среда не настроена)
3. **PR не создан** — согласно инструкции, PR открывает менеджер

## Миграции

Миграций нет — изменения только в логике рендеринга и API, схема БД не менялась.

## Рекомендации по тестированию

Для полного прогона тестов на локальной машине:

```bash
# Создать БД
PGPASSWORD=... createdb -h localhost -U trainer_crm -p 5433 trainer_crm_test_t207

# Переменные окружения
export DATABASE_URL="postgresql+asyncpg://trainer_crm:<pass>@localhost:5433/trainer_crm_test_t207"
export DATABASE_URL_SYNC="postgresql+psycopg://trainer_crm:<pass>@localhost:5433/trainer_crm_test_t207"
export PYTEST_RELAX_DATABASE_NAME=1
export TELEGRAM_BOT_TOKEN="123456789:AAH-dummy"
export TELEGRAM_BOT_TOKEN_CLIENT="123456789:AAH-dummy"
export TELEGRAM_BOT_TOKEN_TRAINER="123456789:AAH-dummy"
export TELEGRAM_BOT_TOKEN_ORG="123456789:AAH-dummy"
export TELEGRAM_BOT_TOKEN_ADMIN="123456789:AAH-dummy"
export ORG_BOT_USERNAME="test_bot"

# Миграции
alembic upgrade head
alembic heads  # должен быть ровно 1 head

# Тесты
pytest  # полный прогон
pytest tests/api/test_arena_schedule_mode.py::test_invalid_phone_not_shown_in_ssr_and_api  # только новый тест

# Node тесты
TZ=UTC node --test tests/js/*.test.js

# Очистка
dropdb -h localhost -U trainer_crm -p 5433 trainer_crm_test_t207
```

## Итого

✅ **AC-3** выполнен: причина расхождения Островца найдена и задокументирована  
✅ **Телефоны** исправлены: невалидные значения не попадают в SSR и API  
✅ **Код** запушен в ветку `fix/TASK-207-ostrovets-phone-guard-f627`  
✅ **Ruff** проверка пройдена  
⚠️ **Полные тесты** требуют настройки среды (PostgreSQL)  
❌ **PR** не создан (по инструкции — ревью делает менеджер)
