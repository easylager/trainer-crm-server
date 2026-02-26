# Стратегия сессии клиента (клиентский бот)

## Цель

Хранить выбор пользователя (город → тренер → далее запись/дата) между шагами и между перезапусками бота, без привязки к одному инстансу (можно несколько воркеров).

## Где хранить

**Таблица в БД `client_sessions`** — один источник правды.

- Переживает рестарты и деплои.
- Один или несколько инстансов бота читают/пишут в одну БД.
- Легко расширять: новые колонки или JSON `payload` для гибких данных.
- Не тянем Redis, пока не нужны TTL/очереди.

## Схема (расширяемая)

| Поле | Тип | Описание |
|------|-----|----------|
| `telegram_id` | BIGINT PK | Идентификатор пользователя в Telegram |
| `state` | VARCHAR(32) | Текущий шаг: `idle`, `picking_city`, `city_selected`, `viewing_catalog`, `trainer_selected`, `booking_datetime`, … |
| `city_id` | INT NULL FK | Выбранный город (справочник `cities`) |
| `selected_service_id` | INT NULL FK | Выбранная услуга (справочник `services`) |
| `selected_trainer_id` | INT NULL FK | Выбранный тренер |
| `payload` | JSONB NULL | Произвольные данные: `service_id`, `pending_date`, `message_id` и т.д. |
| `updated_at` | TIMESTAMPTZ | Время последнего обновления (для отладки и опционального TTL) |

Один ряд на пользователя: вставка при первом обращении, дальше только UPDATE.

## Поток (сейчас и дальше)

1. **Сейчас (минимально)**  
   - `/start` → есть кнопка «Каталог тренеров».  
   - Каталог → список активных тренеров; у каждой карточки кнопка «Выбрать».  
   - «Выбрать» → пишем в сессию `selected_trainer_id`, `state = trainer_selected`, показываем «Выбран: Имя. Дальше: запись / написать / назад».

2. **Город и услуга**  
   - Справочники `cities` и `services`; в профиле тренера — `city_id`.  
   - Перед каталогом: «Выбери город» → сохраняем `city_id`, затем «Выбери услугу» → сохраняем `selected_service_id`, затем каталог (фильтр по city_id и service_id в API).  
   - В сессии хранятся `city_id`, `selected_service_id`, `selected_trainer_id`.

3. **Дальше: запись**  
   - Кнопка «Записаться» → `state = booking_datetime`, в `payload` можно класть выбранную услугу, дату и т.д.  
   - Все шаги опираются на ту же таблицу и при необходимости на `payload`.

## Слой приложения

- **Repository** `ClientSessionRepository`: get_by_telegram_id, upsert(telegram_id, state=?, city_id=?, selected_trainer_id=?, payload=?).  
- **Use cases** (application): get_or_create_session(telegram_id), set_selected_trainer(telegram_id, trainer_id), set_city(telegram_id, city_id), clear_selection(telegram_id) и т.п.  
- **Бот**: в хендлерах только вызов use case + ответ пользователю (без SQL).

## Итог

- Сессия = одна строка в БД на `telegram_id`.  
- Состояние и выбор (город, тренер, запись) хранятся в колонках и при необходимости в `payload`.  
- Сначала делаем выбор тренера и кнопку «Выбрать» с сохранением в `client_sessions`; город добавляем следующим этапом по той же схеме.
