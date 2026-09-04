---
task_id: TASK-047
title: Полный охват валютного отображения — бот + вебапп JS
status: READY
phase: new
priority: LOW
created_at: 2026-09-04
updated_at: 2026-09-04
---

# Task

## Objective

Довести до конца то, что [[TASK-043]] сознательно не стала делать целиком: заменить
все оставшиеся места, где сумма форматируется как захардкоженный текст `BYN`, на
валютно-зависимое отображение (RUB для RU-города) и, где применимо, на знак НБРБ вместо
текста для BYN.

## Business Context

Побочный продукт реализации [[TASK-043]] (2026-09-04) — при разведке нашлось ~13 мест в
`src/bot/*` (форматирование Telegram-сообщений) и ~30 захардкоженных строк `' BYN'` в
10 файлах `static/webapp/*.js`, которые не были тронуты сознательно: (1) сейчас нет ни
одного реального RU-тренера — RU-тарифы появятся только после [[TASK-044]], поэтому
отсутствие RUB в этих местах пока не видно ни одному живому пользователю; (2) большинство
bot-сообщений — чистые форматирующие функции без доступа к сессии БД/`trainer_id`,
threading валюты через них — самостоятельный рефактор, а не точечная правка; (3) джаваскрипт
не имеет центрального форматтера цены (в отличие от `byr_currency_display.py` на бэкенде) —
почти каждый файл дублирует свою версию `+ ' BYN'`.

**Why:** сделано осознанно, не по недосмотру — см. TASK-043 Comprehension Tips/Next Action.
**Обновление 2026-09-04:** владелец продукта проверил вручную сразу после TASK-043/044/045 и
увидел `BYN` в профиле и в подписке — это ускорило часть работы: `trainer-subscription.html`
(все 9 мест) и суффикс цены в `trainer-profile-main.js` уже сделаны валютно-осведомлёнными
в рамках TASK-043 (см. её DEC-004/EDGE-003), а не ждали этой задачи. Также нашли и поправили
причину, по которой фронтенд-правки не были видны в браузере: `theme.css`/`catalog-main.js`/
`trainer-profile-main.js` кэшируются браузером на год по версии в `?v=...` — при следующих
правках **обязательно поднимать версию** в каждом HTML, который подключает файл, иначе
исправление никто не увидит.
**How to apply:** оставшийся объём (боты + ~8 файлов вебаппа) можно начинать в любой момент —
не обязательно ждать реального RU-тренера, раз владелец продукта уже тестирует вручную сменой
города.

## Scope

### In Scope

- `src/bot/messages.py`, `src/bot/admin_moderation_card.py`, `src/bot/trainer_digest_format.py`,
  `src/bot/handlers/trainer_handlers.py`, `src/bot/handlers/client_handlers.py`: протянуть
  валюту (`src.shared.currency.resolve_trainer_currency`/`resolve_currency`) туда, где сейчас
  вызывается `format_rubles_byn_display`/`format_kopeks_byn_display` без параметра `currency`.
- `static/webapp/*.js` (admin-analytics-shared, client-requests-main,
  client-saved-trainers-main, schedule-editor-main, trainer-stats-main, trainer-clients-main,
  trainer-pass-products-main, trainer-home-main) — `catalog-main`/`trainer-profile-main` уже
  сделаны (TASK-043 DEC-004). Завести общий
  JS-хелпер форматирования цены (по образцу обновлённого `trainer-card-shared.js`
  `formatPriceBynHtml(amount, currency)`) и заменить локальные `+ ' BYN'` на него; передавать
  `currency`/знак НБРБ туда, где API уже отдаёт `price_byn`.
- Возможно потребуется добавить `currency`/`price_group` в API-ответы, которые сейчас отдают
  только `price_byn` без указания валюты (проверить по месту).

### Out of Scope

- Сама техническая база (резолв валюты, шрифт, bePaid) — уже сделана в [[TASK-043]].
- RU-тарифы — [[TASK-044]].

## Comprehension Tips

### Facts

- `src.shared.currency.resolve_trainer_currency(session, trainer_id)` уже существует и
  протестирован (`tests/shared/test_currency.py`) — переиспользовать, не писать заново.
- `format_rubles_byn_display`/`format_kopeks_byn_display` уже принимают опциональный
  `currency` (default `"BYN"`, обратная совместимость) — см.
  `src/shared/byr_currency_display.py`, `tests/shared/test_byr_currency_display.py`.
- В вебаппе с TASK-043 живой пример — `static/webapp/trainer-card-shared.js`
  `formatPriceBynHtml` и один живой вызов в `static/webapp/catalog-main.js` (price-tier радио
  в модалке бронирования каталога) уже валютно-осведомлены (RUB → `₽`, BYN → знак НБРБ через
  `.nbrb-icon`); `trainer-card-shared.js` сам по себе НЕ подключён ни на одной странице
  (мёртвый файл, orphaned) — по пути обнаружился и исправлен не связанный баг
  (`formatPriceByn: formatPriceByn` — ссылка на неопределённую переменную,
  `window.TrainerCardShared` падал при загрузке); остальные ~9 файлов не тронуты.

## Acceptance Criteria

### AC-001
Все Telegram-сообщения с ценой для тренера/клиента из RU-города показывают `₽`, а не `BYN`.
Requirement: INFERRED
Verification method: manual
Result: NOT_VERIFIED

### AC-002
Все места в вебаппе, показывающие цену в BYN, используют знак НБРБ вместо текста `BYN`; для
RU-города показывают `₽`.
Requirement: INFERRED
Verification method: manual
Result: NOT_VERIFIED

## Next Action

Не начинать до появления хотя бы одного реального RU-тренера через [[TASK-044]] — иначе
верифицировать нечем.
