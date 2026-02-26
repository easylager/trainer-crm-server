# Скрипты проверки и доказательств (booking complete + feedback)

## Требования

- Из корня проекта, с настроенным `.env` (или `DATABASE_URL` в окружении).
- БД с применённой миграцией `0025_booking_completed_and_reviews`.

---

## 1. Полный evidence-прогон (рекомендуется)

Создаёт тестовые данные (слот вчера 10:00–11:00 + pending-запись), прогоняет логику завершения и отзывов, проверяет каждый шаг и пишет лог.

```bash
python -m scripts.run_booking_evidence
```

- **Шаги:** создание trainer/slot/booking → `list_bookings_to_complete` → `mark_booking_completed_and_notify` → проверка `status=completed` и строки в `booking_completed_notifications` → клиентский отзыв (рейтинг + текст) → отзыв тренера → проверка `trainer_ratings` и `trainer_review_text`.
- **Результат:** вывод в консоль + файл `logs/evidence_booking_YYYYMMDD_HHMMSS.log`.
- **Код выхода:** 0 — все проверки прошли, 1 — есть падения.

---

## 2. Проверка «что бы завершилось на следующем тике»

Только чтение: какие записи сейчас подходят под авто-завершение (pending + слот уже в прошлом).

```bash
python -m scripts.check_pending_complete
```

Удобно перед/после ручного теста или чтобы убедиться, что воркер что-то найдёт.

---

## Контроль по логам

- В **client_app** в цикле завершения записей уже стоят принты: `[booking_complete_loop] tick`, `found N bookings`, `completing booking_id=...`, `sent ... to client`.
- После прогона evidence смотри `logs/evidence_booking_*.log` — там по шагам зафиксировано, что логика завершения и отзывов сработала и данные в БД обновились как ожидается.
