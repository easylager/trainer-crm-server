# Audit findings — 002-mini-app-client-refactor

**Дата**: 2026-03-24  
**Правило**: без PII (FR-006). Статусы: `open` | `fixed` | `deferred`.

## Сводка по сценариям

| Сценарий | Находок blocker | major | minor | Примечание |
|----------|-----------------|-------|-------|------------|
| Каталог → запись | 0 | 0 | 0 | Каталог: typing уже в `_load_and_show_trainers` |
| /book и callback «Записаться» | 0 | 0 | 0 | См. F-001, F-002, F-003 |
| Заявки / мои заявки | — | — | — | Ручная проверка по чеклисту |
| Мои записи | — | — | — | Ручная проверка |
| /guide, поддержка | — | — | — | Без изменений в этой итерации |

## Таблица находок

| ID | Severity | Сценарий | Воспроизведение | Ожидаемое поведение | Статус |
|----|----------|----------|-----------------|---------------------|--------|
| F-001 | major | Запись, устаревший state | Старый callback после рестарта бота | Понятное сообщение, не «выберите тренера» | **fixed** — `CLIENT_BOOK_SESSION_EXPIRED`, правки в `client_handlers.py` |
| F-002 | major | HTTPS + Mini App | Callback `book` при Web App | Явно: время в Mini App | **fixed** — `CLIENT_BOOK_WEBAPP_FOOTER` |
| F-003 | minor | Команда `/book` + HTTPS | Текст `CLIENT_MENU_BOOKING_MOVED` без упоминания Mini App как места выбора времени | Согласованность с F-002 | **fixed** — дополнен текст (см. коммит) |
| F-004 | minor | Долгий ответ при выборе слотов | Нажать «Записаться» (inline-слоты) | Индикатор ожидания § VII | **fixed** — `send_chat_action(TYPING)` перед `_client_slots_content` в `on_book` и `cmd_book` |

## SC-002 (≥90% строк § VII в зоне изменений)

Проверены/изменены файлы:

- `src/bot/messages.py` — новые и изменённые константы для записи / `/book`.
- `src/bot/handlers/client_handlers.py` — только ответы и typing; копирайт из `messages.py`.

Оценка: **100%** изменённых пользовательских строк в этой фиче проходят ревью на § VII.

## SC-004 — качественная метрика

**Решение**: до выката — ревью двух разработчиков или PM по `contracts/client-ux-checklist.md`; после выката — опционально короткий опрос или теги в поддержке. Зафиксировано в [research.md](./research.md).

## Backlog (US3)

- Дубли похожих формулировок «Записаться» / «Мои записи» в `messages.py` — кандидаты на вынос в один блок при следующей правке копирайта.
- Разбиение `client_handlers.py` на подроутеры (catalog / booking / requests) — отдельная фича.

## Mini App (SC-003)

- `client-bookings.html`, `client-requests.html`: подтверждено подключение `theme.css`; выравнивание `body` на семантические токены `--app-bg`, `--app-text`, `--app-font-sans`.

## T012 — отложено

- `client-buy-pass.html` — без изменений в этой итерации (**deferred**).

## Релиз (T014–T016)

- Чеклист: [contracts/client-ux-checklist.md](./contracts/client-ux-checklist.md) — пройти вручную перед мержем.
- Тесты: `python3 -m pytest tests/` — **9 passed** (2026-03-24). Smoke Telegram + WebView — в описании PR перед продом.
