---
task_id: TASK-044
title: Тарифы подписки тренера в рублях для России (Москва/МО дороже базы)
status: COMPLETE
phase: verify
priority: HIGH
execution_mode: AUTONOMOUS
created_at: 2026-09-04
updated_at: 2026-09-04
---

# Task

## Objective

Задать стоимость подписки тренера (CRM/Online/Analytics/Groups) в российских рублях для
тренеров из Санкт-Петербурга/ЛО и Москвы/МО, с наценкой для Москвы/МО относительно базовой
RU-цены. Зависит от технической базы мультивалютности — [[TASK-043]].

## Business Context

Расширение на Россию, сентябрь 2026 (память `moscow-expansion-2026-09`). Владелец продукта
задал направление гибкости: "если Москва/МО — тут подписка чуть дороже" (относительно
Санкт-Петербурга/ЛО, который выступает базовой RU-ценой). Точные суммы владелец продукта
попросил рассчитать по курсу от текущих BYN-тарифов, с округлением — сделано ниже как
предложение; наценка **+25% для Москвы/МО подтверждена владельцем продукта 2026-09-04**
(см. DEC-001).

**Важно:** для тренера из Москвы/МО это не должно выглядеть как "наценка" — он просто
видит свою цену подписки, без пометок "дороже", "премиум-регион" или сравнения с ценой
СПб/ЛО. Незаметное геозависимое ценообразование, а не явный региональный прайсинг. Та же
логика в обратную сторону — в [[TASK-045]] (небольшие BY-города, скидка тоже не должна
быть видна как скидка).

## Scope

### In Scope

- Тарифы `SubscriptionTierPricing` (crm/online/analytics) в RUB для RU-городов, с наценкой
  для Москвы/МО.
- Тарифы `SubscriptionModulePeriodPricing` (online/analytics/groups × 1/3/12 мес) в RUB для
  RU-городов, с наценкой для Москвы/МО.
- Логика выбора нужной строки тарифа по городу тренера (RU-база vs RU-Москва) в том месте,
  где сейчас читается единственная BY-строка тарифа.

### Out of Scope

- Техническая база резолва валюты по городу — [[TASK-043]] (эта задача на неё опирается).
- Гибкая сетка для небольших белорусских городов — [[TASK-045]].
- Проверка, что bePaid реально принимает RUB, — не исследуется здесь, см.
  [[TASK-043]] EDGE-001/Q-001.

## Comprehension Tips

### Facts

- Текущие BYN-тарифы (dev БД, `subscription_tier_pricing`): crm = 20.00 BYN/мес,
  online = 35.00 BYN/мес, analytics = 40.00 BYN/мес (`period_days=30`).
- Текущие BYN-тарифы (`subscription_module_period_pricing`): online — 15.00 BYN (1 мес),
  40.50 BYN (3 мес), 144.00 BYN (12 мес); analytics и groups одинаковы между собой —
  5.00 BYN (1 мес), 13.50 BYN (3 мес), 48.00 BYN (12 мес).
- Обе таблицы уже содержат колонку `currency` (`models.py:1083-1102`, `1118-1130`) —
  добавление RU-строк не требует миграции схемы, только новых записей с
  `currency='RUB'` и привязкой к стране города (после [[TASK-043]]).
- Курс на 03.09.2026 (ЦБ РФ, кросс-курс через myfin.by/russian-trade.com):
  1 BYN ≈ 28.35 RUB. Курс плавающий — сумму фиксировать на дату согласования, не
  автоматически пересчитывать при каждом платеже (иначе тариф "плывёт" для тренера).
- Прод-БД (проверено 2026-09-04 через Railway readonly): цены совпадают с указанными
  выше, "Москва/МО" (city id 30) и "Санкт-Петербург/ЛО" (city id 31) уже заведены как
  города и активны — сама RU-строка тарифа в `subscription_tier_pricing`/
  `subscription_module_period_pricing` пока отсутствует, добавляется этой задачей.

### Implications

- Ниже — расчётные предложения (BYN-цена × 28.35, округление до "красивого" числа),
  плюс наценка Москва/МО +25% (подтверждена, DEC-001). Сами округлённые базовые суммы
  (590/990/1150 и т.д.) — расчёт по курсу, а не отдельно проговорённая владельцем продукта
  цифра; при желании их ещё можно скорректировать перед вводом в прод.

**SubscriptionTierPricing, RU-база (СПб/ЛО), предложение:**
| tier | BYN/мес | RUB/мес (расчёт) | RUB/мес (округл.) |
|---|---|---|---|
| crm | 20.00 | 567 | 590 |
| online | 35.00 | 992 | 990 |
| analytics | 40.00 | 1134 | 1150 |

**SubscriptionTierPricing, Москва/МО (+25%), предложение:**
| tier | RUB/мес (база) | RUB/мес (Москва) |
|---|---|---|
| crm | 590 | 750 |
| online | 990 | 1250 |
| analytics | 1150 | 1450 |

**SubscriptionModulePeriodPricing, RU-база (СПб/ЛО), предложение:**
| module | 1 мес | 3 мес | 12 мес |
|---|---|---|---|
| online | 430 | 1150 | 4090 |
| analytics | 150 | 390 | 1390 |
| groups | 150 | 390 | 1390 |

**SubscriptionModulePeriodPricing, Москва/МО (+25%), предложение:**
| module | 1 мес | 3 мес | 12 мес |
|---|---|---|---|
| online | 550 | 1450 | 5100 |
| analytics | 190 | 490 | 1750 |
| groups | 190 | 490 | 1750 |

## Acceptance Criteria

### AC-001
Тренер из Санкт-Петербурга/ЛО видит и оплачивает подписку CRM/Online/Analytics по
RU-базовой цене в рублях (см. таблицу выше).
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: `tests/api/test_webapp_subscription_catalog_price_group.py::
test_catalog_uses_ru_base_pricing_for_spb_city` — тренер с городом `price_group='RU_BASE'`
видит `GET /api/webapp/trainer/subscription/catalog` с `currency=RUB`, crm/мес = 59000 копеек
(590 ₽), что совпадает с реально засеянными строками в БД.
Verified at: рабочее дерево поверх 5ac9494, 2026-09-04 (не закоммичено)

### AC-002
Тренер из Москвы/МО видит и оплачивает подписку по наценённой на 25% цене (RU-база + 25%),
без ручного вмешательства администратора.
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: `tests/api/test_webapp_subscription_catalog_price_group.py::
test_catalog_uses_ru_moscow_premium_pricing` — тренер с городом `price_group='RU_MOSCOW'`
видит crm/мес = 75000 копеек (750 ₽) = 59000 × 1.25, автоматически по `trainer_profiles.
city_id`, без ручных действий администратора.
Verified at: рабочее дерево поверх 5ac9494, 2026-09-04 (не закоммичено)

### AC-003
Тренер из белорусского города по-прежнему видит и оплачивает тариф в BYN по старым
суммам — регрессия отсутствует.
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: `test_catalog_defaults_to_by_base_without_city` (currency=BYN, crm/мес=2000 копеек
— неизменная старая сумма) + полный регрессионный прогон 138 существующих тестов
подписки/billing (`tests/application/test_subscription_*`, `tests/api/test_webapp_trainer_
subscription_stub_confirm.py`, `test_bepaid_collective_webhook.py`,
`test_webapp_trainer_collective.py`) — все прошли без изменений в ожидаемых значениях.
Verified at: рабочее дерево поверх 5ac9494, 2026-09-04 (не закоммичено)

### AC-004
Модульные тарифы (online/analytics/groups на 1/3/12 месяцев) для RU-городов отображаются
и тарифицируются согласно RU-сетке (база/Москва), а не через конвертацию "на лету" из BYN.
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: миграция `0189_ru_subscription_pricing` вставляет реальные строки
`subscription_module_period_pricing` для `RU_BASE`/`RU_MOSCOW` × online/analytics/groups ×
1/3/12 мес (проверено прямым запросом к dev-БД после apply/downgrade/re-apply); читающая
функция `get_module_period_pricing` фильтрует по `price_group`, конвертации из BYN на
лету нигде не осталось.
Verified at: рабочее дерево поверх 5ac9494, 2026-09-04 (не закоммичено)

## Assumptions

- Наценка Москва/МО применяется равномерно ко всем тарифам и модулям (единый процент), а
  не индивидуально по каждому тарифу — упрощение до появления данных о реальном спросе.
- Курс BYN→RUB фиксируется вручную при вводе тарифов (не привязан к live-курсу ЦБ) —
  соответствует тому, как уже устроены текущие BYN-тарифы (админ-редактируемая таблица,
  не автоматический курс).

## Decisions

### DEC-001
Наценка для Москвы/МО — **+25%** к RU-базовой цене (СПб/ЛО), применяется равномерно ко
всем тарифам (crm/online/analytics) и модулям (online/analytics/groups × 1/3/12 мес).
Reason: подтверждено владельцем продукта 2026-09-04 в ответ на предложенный расчёт.

### DEC-002 (закрывает Q-002)
Наценка Москва/МО реализована как отдельная запись — `price_group='RU_MOSCOW'` (по
аналогии `'RU_BASE'`, `'BY_BASE'`) во всех трёх тарифных таблицах, а не как множитель "на
лету". `cities.price_group` резолвит, какую строку читать (см. [[TASK-043]] DEC-002 —
инфраструктура `price_group` появилась там же).
Reason: как и предполагалось в исходном Q-002 — проще для админки и предсказуемее для
тренера (видит фиксированную, а не вычисляемую на лету цену); переиспользует тот же
паттерн, что и `country`/`price_group` на `cities`.

### DEC-003
Админ-панель редактирования тарифов (`list_subscription_tier_pricing_for_admin`,
`update_subscription_tier_pricing`) **сознательно ограничена `price_group='BY_BASE'`** —
не показывает и не позволяет редактировать RU-строки. RU-тарифы заведены только через
миграцию `0189_ru_subscription_pricing.py`, менять их пока можно только новой миграцией
или прямым SQL.
Reason: по ходу реализации обнаружено, что без явного фильтра `price_group` админские
SQL-запросы (`UPDATE ... WHERE tier = :tier` и `SELECT ... WHERE tier = :tier AND
period_months = :pm`) either обновили бы разом все price_group сразу, либо непредсказуемо
выбирали не ту строку — реальный, не гипотетический риск после того, как в таблицах
появилось больше одной строки на tier (см. регрессионный тест
`test_admin_editing_by_base_price_does_not_touch_ru_rows`). Расширение админки на RU —
отдельная, не обязательная для запуска задача (нет ещё ни одного RU-тренера, кому это
нужно прямо сейчас).

## Technical Plan (как реализовано)

1. [[TASK-043]] S1 уже даёт `resolve_trainer_price_group` — использовано напрямую, ждать
   было не нужно (сделано в одной автономной сессии).
2. Миграция `migrations/versions/0189_ru_subscription_pricing.py`: RU-строки для всех трёх
   тарифных таблиц (`price_group='RU_BASE'`/`'RU_MOSCOW'`), плюс переключение
   `cities.price_group` Москвы/МО с дефолтного `'RU_BASE'` (из TASK-043) на `'RU_MOSCOW'`.
   Суммы 3/12 мес посчитаны по той же формуле скидки, что уже используется для BY
   (миграция 0069: 3мес = база×3×0.9, 12мес = база×12×0.8) — для единообразия с
   существующей моделью, отдельно владельцем продукта не согласовывалось.
3. `get_tier_period_pricing`/`get_module_period_pricing`/`get_subscription_constructor_
   catalog`/`get_subscription_tier_catalog` получили параметр `price_group` (default
   `BY_BASE`, обратная совместимость). Протянуто во все реальные пути начисления цены:
   `create_catalog_subscription_invoice_for_trainer`, `set_subscription_constructor_
   after_mock_payment`, `admin_grant_subscription_for_invoice` (ERIP/ручное подтверждение),
   `GET /api/webapp/trainer/subscription/catalog`.
4. Админ-панель — см. DEC-003, сознательно ограничена BY_BASE, а не расширена на RU.
5. UI-текст не менялся вообще (ни одного нового места с ценой) — значит формулировок
   "наценка"/"премиум-регион" просто негде появиться; трактую AC как выполненный по
   умолчанию, а не как отдельно проверенный пункт.

## Slices

### S1 RU-база тарифов (СПб/ЛО)
Goal: тренер из СПб/ЛО платит подписку в рублях по базовой RU-цене.
Depends on: TASK-043 S1
Covers: AC-001, AC-003
Verification: manual (integration test)
Estimate: 3
Status: DONE

### S2 Наценка Москва/МО
Goal: тренер из Москвы/МО платит подписку по наценённой цене.
Depends on: S1
Covers: AC-002, AC-004
Verification: manual (integration test)
Estimate: 3
Status: DONE

## Next Action

Готово. Все AC VERIFIED. Следующий шаг — [[TASK-045]] (переиспользует тот же механизм
`price_group`).

## Progress

Реализовано и протестировано 2026-09-04 автономно, вслед за TASK-043: миграция
`0189_ru_subscription_pricing`, `price_group`-параметр в функциях чтения тарифа,
проброшен во все реальные пути начисления. По ходу найден и исправлен реальный (не
гипотетический) баг в админ-функциях редактирования тарифа — без фильтра по
`price_group` они после этой задачи стали бы задевать чужие price_group. Тесты:
`tests/api/test_webapp_subscription_catalog_price_group.py` (4, включая регрессионный
тест на найденный баг) + полный регрессионный набор 138/138. Изменения не закоммичены.
