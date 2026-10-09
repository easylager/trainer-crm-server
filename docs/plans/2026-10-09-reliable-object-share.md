# Надёжный шаринг конкретного объекта (TASK-223)

Дата: 2026-10-09. Ветка `feat/TASK-223-reliable-object-share`, один PR.
Цель MVP: приглашённый попадает ровно на ту арену / тот сеанс, которым с ним поделились, и может переслать дальше.

## Что уже есть (не ломать)

- Страница `/p/{city}/{slug}` с `?s=<session>` и `?i=1`, свой `og:image` на сеанс (`/session/{id}/og.png`), `noindex` для `?s=`/`?i=1`.
- Диплинки Mini App `arena_<id>[_s_<session>]` и `catalog_…` (`place_links.py`, `mini-app-client-shell.js`), запасной путь через `/start`.
- «Позвать / Поделиться» на карточке арены, `client_share_events`, `catalog_consumer_events`.

## Гэпы и потоки работ

| № | Гэп | Поток | Владелец файлов |
|---|---|---|---|
| P0-1 | `ice_sessions.id` пересоздаётся при каждом парсинге (`DELETE`+`INSERT` в `publish.py`), ссылка на сеанс живёт до следующего прогона (45 мин днём) | A | `src/ingestion/publish*.py`, `tests/ingestion/` |
| P0-2 | В Mini App нет состояния «сеанса уже нет», кнопка «Позвать на …» молча берёт другой слот | B | `static/webapp/arena-card*.{js,css}` |
| P1-3 | Нет учёта «пришёл по шарингу»: в `public_page_view` нет `s`/`i`/канала | C + D | `place_links.py`, `public_place_page.py`, `catalog_consumer_*` и шит |
| P1-4 | Диплинк Mini App обрабатывается после загрузки стартовой страницы | D | `mini-app-client-shell.js`, `client-home.html` |
| P1-5 | Настройка «Main Mini App» у бота не проверяется (`client_bot_main_mini_app=True` по умолчанию) | E | `src/bot/`, `src/shared/config.py`, `docs/ops/` |
| P1-7 | В шите Mini App нет прямых Viber / WhatsApp | D | `mini-app-share-sheet.{js,css}` |
| P2 | Состояние «сеанс убрали» на вебе, кэш картинки сеанса, OG-мелочи | C | `place_page.py`, `public_place_page.py`, `static/share/place.html` |
| — | Нет контрактного теста «py-парсер диплинка == js-парсер» | E | `tests/contract/` |

## Контракты между потоками

1. **Параметр канала `src`** в ссылке шаринга: `tg`, `vb`, `wa`, `vk`, `copy`, `story`, `sys`, `img`. Неизвестное значение игнорируется. Список живёт в `place_links.SHARE_SRC_VALUES`; шит (`mini-app-share-sheet.js`) добавляет `src` в момент нажатия канала; страница и `open-telegram` пишут его в `payload` события.
2. **`start_param` не меняется** (`arena_<id>[_s_<session>]`): три парсера (py, shell, arena-card-model) остаются совместимыми.
3. **ID сеанса стабилен**: естественный ключ `(arena_id, starts_at_utc, kind)` (уникальный индекс `uq_ice_sessions_parser_slot` уже есть). Публикация обновляет совпавшие строки, вставляет новые, удаляет только исчезнувшие.
4. Никто, кроме менеджера, не делает `git commit/push/checkout/stash`.

## Проверка

- Без БД: `pytest tests/unit tests/contract`, `node --test tests/js/`.
- С БД (`trainer_crm_test`): CI на PR. Локального Postgres нет.
