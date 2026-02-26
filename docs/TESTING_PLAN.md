# План автотестов (MVP)

## Цели

- Критичные сценарии не ломаются при изменениях.
- Регрессии по БД и API отлавливаются до деплоя.
- Минимум поддержки: тесты быстрые, стабильные, на одной БД (тестовая).

---

## Стек

| Компонент | Выбор |
|-----------|--------|
| Runner | **pytest** |
| Async | **pytest-asyncio** |
| API | **httpx** (async) или **TestClient** (FastAPI) |
| БД | **PostgreSQL** — отдельная БД `trainer_crm_test` или тот же URL с транзакционным откатом (см. ниже) |

Почему не SQLite: в коде есть Postgres-специфика (например `now()`, типы); проще один движок.

---

## Уровни тестов

### 1. Интеграционные (application + БД)

**Где:** `tests/integration/` (или `tests/application/`).

**Что тестируем:**

- **booking_use_cases**
  - `create_booking` — слот available → бронь создаётся, слот становится booked; неверный slot_id/trainer_id → None.
  - `generate_reminders_for_booking` — после создания брони появляются строки в `reminders` (24h/2h по правилам).
  - `list_pending_reminders` — только pending и send_at <= now; отменённая бронь не попадает.
  - `mark_reminder_sent` / `mark_reminder_failed` — статус и поля обновляются.
  - `list_bookings_to_complete` — только pending, слот в прошлом.
  - `mark_booking_completed_and_notify` — статус completed, запись в `booking_completed_notifications`.
- **trainer_use_cases** (по желанию): создание/обновление профиля, рейтинг.

**Фикстуры:** сессия БД (async), при необходимости создание тестовых сущностей (тренер, слот, город, услуга).

### 2. API

**Где:** `tests/api/`.

**Что тестируем:**

- **GET /health** — 200, в теле `db: ok`; при недоступной БД — 503 (можно мокать сессию или использовать тестовую БД).
- **GET /api/trainers** — 200, структура списка (опционально).
- **POST /api/trainers** + **PATCH .../profile** — создание и обновление (интеграция с БД).

### 3. E2E (один критичный сценарий)

**Где:** `tests/e2e/` или один файл `tests/test_booking_flow_e2e.py`.

**Сценарий:** как в `scripts/run_booking_evidence.py` в сжатом виде:

1. Создать тренера (или взять существующего), слот в прошлом, pending-бронь.
2. Вызвать `list_bookings_to_complete` → наша бронь в списке.
3. Вызвать `mark_booking_completed_and_notify` → статус completed, строка в `booking_completed_notifications`.
4. (Опционально) клиентский отзыв, отзыв тренера — проверка, что записи сохраняются.

Без реальной отправки в Telegram; только БД и use cases.

---

## Инфраструктура тестов

### База данных

- **Вариант A:** отдельная БД `trainer_crm_test`. В CI и локально: `DATABASE_URL` указывает на неё; перед тестами `alembic upgrade head`.
- **Вариант B:** та же БД, но каждый тест/модуль работает в транзакции с откатом — изоляция без пересоздания схемы (реализуется фикстурой в conftest).

Рекомендация для старта: **вариант A** — одна тестовая БД, простой сетап.

### conftest.py

- Общая настройка pytest-asyncio (mode=auto или маркеры).
- Фикстура **async session** (или **session_factory**) на тестовую БД.
- При необходимости: фикстуры **trainer**, **slot**, **city**, **service** для вставки тестовых данных.

### Запуск

```bash
# Все тесты (нужна поднятая Postgres и DATABASE_URL / DATABASE_URL_TEST)
pytest

# Только интеграция
pytest tests/integration/

# Только API
pytest tests/api/

# С покрытием
pytest --cov=src --cov-report=term-missing
```

---

## Порядок внедрения

| Шаг | Действие | Статус |
|-----|----------|--------|
| 1 | Подключить pytest, pytest-asyncio; добавить `tests/`, `conftest.py`, фикстуру сессии на тестовую БД. | ✅ |
| 2 | Написать 2–3 интеграционных теста на booking_use_cases (create_booking, reminders, list_pending_reminders / complete). | ✅ |
| 3 | Тест GET /health (и при желании один тест на GET /api/trainers). | ✅ |
| 4 | Один E2E-тест «запись → завершение → отзывы» (без Telegram). | ✅ |
| 5 | API: GET /api/trainers, GET /api/public/trainers. | ✅ |
| 6 | CI (GitHub Actions): Postgres service, миграции, pytest. | ✅ `.github/workflows/tests.yml` |

---

## Файловая структура (целевая)

```
tests/
  conftest.py           # pytest-asyncio, session, опционально test data fixtures
  integration/
    test_booking_use_cases.py
    test_trainer_use_cases.py  # опционально
  api/
    test_health.py
    test_trainers_api.py      # опционально
  e2e/
    test_booking_complete_flow.py
```

Сначала достаточно: `conftest.py` + `tests/integration/test_booking_use_cases.py` + `tests/api/test_health.py`.

---

## Как запустить тесты

```bash
# Установить зависимости (в т.ч. pytest, pytest-asyncio, pytest-cov, httpx)
pip install -r requirements.txt

# Поднять Postgres (docker compose up -d postgres), создать тестовую БД и накатить миграции:
createdb trainer_crm_test
DATABASE_URL=postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm_test alembic upgrade head

# Запуск (из корня проекта; DATABASE_URL должен указывать на тестовую БД)
export DATABASE_URL=postgresql+asyncpg://trainer_crm:trainer_crm_dev@localhost:5432/trainer_crm_test
pytest

# Только интеграция
pytest tests/integration/ -v

# С покрытием
pytest --cov=src --cov-report=term-missing
```
