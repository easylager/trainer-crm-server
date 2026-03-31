# Quickstart: 005-trainer-profile-details

1. Создать тренера: `POST /api/trainers`.
2. Обновить профиль: `PATCH /api/trainers/{id}/profile` с новыми полями.
3. Получить профиль: `GET /api/trainers/{id}` и проверить выдачу новых блоков.
4. Проверить справочники: endpoint(ы) опций для select.
5. Прогнать тесты: `python3 -m pytest tests/api/test_trainers_api.py -q`.
