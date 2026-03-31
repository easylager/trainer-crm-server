# Epic C — отчёт (API authorization, IDOR, public payloads, uploads)

Дата: 2026-03-30.

## SEC-C1 — Аудит `/api/webapp/...`

**Правило:** субъект всегда из валидного `initData` нужного бота; `trainer_id` / `client_id` из БД по `telegram_id`, не из доверия к произвольным полям тела для смены пользователя.

| Область | Механизм |
|---------|----------|
| Тренер (schedule, stats, passes, subscription, certificates, …) | `get_trainer_id_by_telegram_id` или `get_trainer_id_linked_any_status` + `_trainer_telegram_id` / `_require_linked_trainer_id` |
| Клиент (`/client/*`) | `_client_telegram_id`; бронирование по `slot_id`/`request_id` с проверкой слота и заявки; отмена через `cancel_booking_by_client(..., telegram_id)` |
| Админ | `_admin_telegram_id` + `admin_telegram_ids` |

**Исключения / особенности:**

- `GET /client/slots?trainer_id=` — намеренно: клиент смотрит слоты выбранного тренера из каталога; доступ к слотам публичных тренеров с онлайн-записью.
- `POST /client/session` — в теле `trainer_id` как выбор фильтра каталога, не идентификация «я — тренер».
- `GET /client/pass-products?trainer_id=` — список продуктов тренера после проверки `_client_telegram_id` и `trainer_allows_online_booking`.

## SEC-C2 — `/api/public/...`

- Ответы `GET /api/public/trainers` и `GET /api/public/trainers/{id}` проходят `sanitize_trainer_for_public_catalog()` — убираются `telegram_id`, поля модерации и `created_at` тренера.
- Клиенты в каталоге не перечисляются; отзывы идут через `list_public_trainer_reviews` (без идентификаторов клиентов).
- Публичная раздача фото по `file_key` под `trainers/` — см. Epic E (ограничение префикса в `get_photo`).

## SEC-C3 — Загрузки и presigned S3

- `register_photo`: ключи должны лежать под `trainers/{trainer_id}/` (`photo_storage_keys_allowed_for_trainer`, иначе `TrainerPhotoFileKeyError`).
- `presign_upload_url`: ключ всегда `trainers/{trainer_id}/{uuid}.ext`; TTL по умолчанию `PHOTO_UPLOAD_PRESIGN_EXPIRES_SEC` (600 с).
- Legacy `POST /api/upload/photo`, `/api/upload/photo/presign`, `POST /api/trainers/{id}/photos` без `initData` **отключены**, если не задан `INTERNAL_UPLOAD_API_KEY`; при заданном ключе нужен заголовок `X-Internal-Upload-Key`.
- Web App: `POST /api/webapp/trainer/photos/presign` и register — `trainer_id` только из `initData`.

## Код

- `src/shared/public_trainer_payload.py` — санитизация каталога.
- `src/application/trainer_use_cases.py` — `photo_storage_keys_allowed_for_trainer`, `TrainerPhotoFileKeyError`, проверка в `register_photo`.
- `src/api/routes/upload.py` — `_require_internal_upload_key`.
- `src/infrastructure/s3.py` — TTL presigned PUT из настроек.
