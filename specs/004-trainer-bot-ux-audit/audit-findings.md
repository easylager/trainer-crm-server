# Audit findings: 004-trainer-bot-ux-audit

**Статус**: итерация 2026-03-24 (код-ревью + правки в репозитории).  
**Без PII.**

## Метод

Статический аудит `src/bot/handlers/trainer_handlers.py` и `src/bot/messages.py` по § VII конституции: отсутствие `send_chat_action`, копипаст пользовательских строк вне `messages.py`, неоднозначные ошибки заявок.

## TrainerScenario (покрытие ревью)

| id | steps (кратко) | channels |
|----|----------------|----------|
| entry_link | /start link_* → привязка или ошибка | bot |
| guide | /guide → текст + поддержка | bot |
| schedule_editor | /editor → Web App или клавиатура шаблона | bot |
| my_bookings | /bookings → Web App или список callback | bot |
| client_requests | /requests → Web App или список заявок | bot |
| clients | /clients → Web App или подсказка HTTPS | bot |
| passes | /passes → Web App или подсказка HTTPS | bot |
| stats | /stats → Web App или текстовая статистика | bot |
| subscription | /subscription → статус + оплата | bot |

## AuditFinding

| id | scenario_id | severity | constitution | repro | expected_ux | status |
|----|---------------|----------|--------------|-------|-------------|--------|
| F-001 | schedule_editor, my_bookings, … | major | § VII (ожидание) | Команды без typing при запросах к БД | Индикация «печатает…» на длинных шагах | fixed |
| F-002 | guide, passes, clients | major | § VII (тексты) | Строки Web App / ошибок захардкожены в хендлере | Единое место в `messages.py`, единый тон «ты» | fixed |
| F-003 | client_requests | minor | § VII | «Заявка не найдена» без hint обновить список | Явная подсказка открыть раздел заново | fixed |
| F-004 | client_requests | minor | § VII | Разные формулировки для одной ошибки payload | Константы `TRAINER_ERROR_REQUEST_*` | fixed |

## BacklogItem

| order | finding_id | user_impact |
|-------|------------|-------------|
| 1 | F-001 | Видимая отзывчивость бота |
| 2 | F-002 | Поддержка копирайта и § VII |
| 3 | F-003, F-004 | Меньше тупиков при устаревших заявках |

## Чеклист contracts/trainer-ux-checklist.md

Полный ручной прогон в Telegram — владельцу фичи; после правок код соответствует пунктам 1–8 (тексты из `messages.py`, HTML-режим, typing на ключевых шагах).

| § | Пункт | ✓/✗ | Заметка |
|---|-------|-----|---------|
| VII | 1–8 | ✓ | см. коммит: typing + константы |
| VIII | — | — | Mini App не менялись в этой итерации |

## Метрики (SC-001, SC-004)

- **SC-001**: сценариев в таблице: **9** ≥ 5; блокирующих находок в код-ревью закрыто (F-001–F-004).
- **SC-004**: замер «до/после» в секундах — выполнить вручную на устройстве при приёмке; добавление `typing` не увеличивает число шагов сценария.
