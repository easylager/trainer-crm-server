# Contract: trainer profile fields

## Purpose

Единый контракт новых полей профиля тренера для create/patch/get.

## API Surface

- `POST /api/trainers`
- `PATCH /api/trainers/{id}/profile`
- `GET /api/trainers/{id}`
- `GET /api/trainers/education-options` (уже существует)

## Validation Rules

- Поля выбора принимают только значения из списка опций.
- Текстовые поля ограничены по длине.
- Неизвестные значения -> 422 с понятным сообщением.

## UI Mapping

- Пустые поля не рендерятся как отдельные секции.
- Секции карточки отображаются в фиксированном порядке для сравнимости.
