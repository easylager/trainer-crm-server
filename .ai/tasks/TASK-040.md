---
task_id: TASK-040
title: Остаток занятий по абонементу не виден в карточке записи
status: COMPLETE
phase: review
priority: MEDIUM
created_at: 2026-09-03
updated_at: 2026-09-03
---

# Task

## Objective

В карточке записи, когда оплата ожидается абонементом, тренер должен сразу видеть
остаток занятий («X из Y») и иметь возможность перейти в этот абонемент одним тапом —
без захода в карточку клиента.

## Business Context

Источник — `.ai/tasks/TASK-003-passes-info-in-booking.md`. Пункт «сделать абонемент
кликабельным из карточки клиента» уже реализован (`trainer-clients-main.js:3596`,
ссылка `tc-pass-link`) — в скоуп этой задачи не входит. Реальный пробел — карточка
записи, где вместо конкретики стоит статичный текст «Абонемент покрывает».

Важно: реальный экран записи — `static/webapp/schedule-editor.html` +
`schedule-editor-main.js` (роутится в `src/api/app.py`). Файл `static/webapp/schedule.html`
нигде не подключён — мёртвый, не трогать, несмотря на внешнее сходство разметки.

## Scope

### In Scope

- `src/application/booking_payment_notice.py` — новая функция, определяющая конкретный
  `pass_instance_id`, покрывающий данную запись (уже погашенный или спроецированный).
- `src/api/routes/webapp.py::get_trainer_booking_detail` — прокинуть новые поля в ответ.
- `static/webapp/schedule-editor-main.js` — заменить статичный текст на кликабельную
  ссылку по образцу `tc-pass-link` из `trainer-clients-main.js`.

### Out of Scope

- Аналогичное для сертификатов (`CERT`) — в брифе не запрошено, симметрия отдельной
  задачей при необходимости.
- Изменение возвращаемого типа `classify_booking_expected_payment_class` /
  `resolve_bookings_expected_payment_class_map` / `_allocate_expected_payment_classes` —
  у них есть другие вызывающие места (3 других эндпоинта в `webapp.py`), которым нужна
  только строка класса; их сигнатуры не меняем, новая функция аддитивна и переиспользует
  их приватные строительные блоки без изменения контрактов.

## Comprehension Tips

### Facts

- `classify_booking_expected_payment_class` (`booking_payment_notice.py:308`) определяет
  только класс `PASS`/`CERT`/`ONE_OFF`/`NONE`, не конкретный `pass_instance_id` — ни для
  ещё не погашенных (виртуальный пул, `_allocate_pass_for_booking`,
  `booking_payment_notice.py:121`), ни для уже погашенных (реальный факт лежит в
  `pass_redemptions`, не читается этим путём).
- Виртуальный пул (`_load_pass_pool_for_client_trainer`, `:177`) уже строится в порядке
  `expires_at ASC NULLS LAST, sessions_remaining ASC` и содержит только активные,
  непросроченные, с `sessions_remaining > 0` абонементы — ровно то же множество, что и
  очередь распределения классов.
- `get_trainer_booking_detail` (`webapp.py:5589-5643`) уже вызывает
  `classify_booking_expected_payment_class` и знает `booking["client_id"]`.
- Карточка рендерит платёжную строку в `openBookingDetail` (`schedule-editor-main.js`,
  функция начинается на строке ~1668, платёжная строка — константа `payPc`/`payValueHtml`
  ближе к концу той же функции): при `payPc === 'PASS'` — статичный `escapeHtml('Абонемент
  покрывает')`.
- Готовый паттерн кликабельной ссылки на абонемент уже есть:
  `trainer-clients-main.js:3596-3598` (`tc-pass-link`, ведёт на
  `trainer-pass-products?pass_instance_id=...&client_id=...&tab=issued`).

### Implications

- Показ конкретного абонемента для ещё не наступившей записи — проекция («если очередь
  распределения не изменится, спишется отсюда»), а не факт. Существующий UI уже
  утверждает это как факт («Абонемент покрывает» без оговорок) — показ «X из Y» не
  добавляет новой неопределённости сверх уже имеющейся, только детализирует её.
- Не меняем сигнатуры «общих» функций пула — добавляем отдельную функцию, переиспользующую
  их приватные помощники (`_load_upcoming_payment_queue_for_client_trainer`,
  `_load_pass_pool_for_client_trainer`, `_pass_entry_covers_booking`) без изменения их
  контрактов, чтобы не задеть три других вызывающих места `classify_booking_expected_payment_class`.

## Acceptance Criteria

### AC-001
Запись с уже погашенным занятием (`pass_redemptions` содержит строку) показывает
реальный использованный `pass_instance_id` и его текущий остаток из БД.
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: tests/application/test_booking_pass_instance_resolution.py::test_resolves_the_actually_redeemed_instance_for_a_past_visit — passed
Verified at: master c1d5d34+, 2026-09-04

### AC-002
Будущая непогашенная запись, которую очередь распределения относит к `PASS`, показывает
тот же `pass_instance_id`, который вернула бы очередь при реальном погашении (при
единственном подходящем активном абонементе).
Requirement: CONFIRMED
Verification method: unit
Result: VERIFIED
Evidence: tests/application/test_booking_pass_instance_resolution.py::test_resolves_the_projected_instance_for_an_unredeemed_future_visit
+ test_returns_none_when_queue_has_no_pass_left_for_this_visit — both passed (3/3 in file)
Verified at: master c1d5d34+, 2026-09-04

### AC-003
Карточка записи при `payPc === 'PASS'` и наличии `pass_instance_id` в ответе показывает
«{имя абонемента}: {остаток} из {всего}» как кликабельную ссылку на
`trainer-pass-products?pass_instance_id=...&tab=issued`; при отсутствии этих полей —
прежний статичный текст «Абонемент покрывает» (деградация без падения).
Requirement: CONFIRMED
Verification method: manual
Result: VERIFIED
Evidence: браузерная проверка (Playwright, замоканный Telegram WebApp init_data, throwaway
тренер с реальной погашенной записью): карточка показала «QA Пробный абонемент: 7 из 10» как
`<a class="tc-pass-link" href="/webapp/trainer-pass-products?pass_instance_id=25&client_id=311&tab=issued">`,
старый статичный текст отсутствует. Деградационная ветка (`else if (payPc === 'PASS')`)
не менялась — код-ревью подтверждает fallback без изменений.
Verified at: uncommitted working tree, 2026-09-04

## Technical Plan

1. `booking_payment_notice.py`: добавить `resolve_pass_instance_for_booking(session,
   booking_id, client_id, trainer_id) -> dict | None` — сначала проверяет
   `pass_redemptions`, иначе повторяет FIFO-проход очереди только по ветке PASS (без
   веток CERT/ONE_OFF, они не нужны), возвращает `pass_instance_id` + свежие
   `sessions_remaining`/`sessions_total`/`product_name` прямым запросом к `pass_instances`.
2. `webapp.py::get_trainer_booking_detail`: при `ppc == "PASS"` вызвать новую функцию,
   положить `pass_instance_id`/`pass_sessions_remaining`/`pass_sessions_total`/
   `pass_product_name` в ответ (`None`, если функция ничего не вернула).
3. `schedule-editor-main.js`: в блоке платёжной строки при `payPc === 'PASS'` и наличии
   `b.pass_instance_id` — рендерить `<a class="tc-pass-link" href=".../trainer-pass-
   products?pass_instance_id=...&client_id=...&tab=issued">` с текстом
   «{product_name}: {remaining} из {total}»; иначе — прежнее поведение.

## Slices

### S1 Бэкенд: конкретный pass_instance_id в ответе карточки записи
Goal: `GET /trainer/bookings/{id}` отдаёт instance/remaining/total при PASS.
Scope: booking_payment_notice.py, webapp.py.
Covers: AC-001, AC-002
Verification: unit-тесты на resolve_pass_instance_for_booking (погашенный / спроецированный случаи)
Estimate: 2
Status: DONE

### S2 Фронтенд: кликабельная строка в карточке записи
Goal: платёжная строка ведёт в абонемент вместо статичного текста.
Scope: schedule-editor-main.js.
Covers: AC-003
Verification: manual (браузер)
Estimate: 1
Status: DONE

## Next Action

Задача завершена. S1 (бэкенд) уже был на master до взятия задачи в работу (попал туда
побочно с TASK-007, коммит b972cbd — включая `resolve_pass_instance_for_booking`, прокидку
полей в `webapp.py` и unit-тесты). Довели S2 (фронтенд) и перепроверили S1.

## Execution History

- **TASK_CREATED** — заведена 2026-09-03, план и слайсы уже готовы.
- 2026-09-04 | обнаружено: S1 (бэкенд, `resolve_pass_instance_for_booking` +
  `get_trainer_booking_detail` + unit-тесты) уже на master — попал туда как часть коммита
  `b972cbd` (TASK-007), не был отражён в статусе этого файла.
- 2026-09-04 | реализован S2: кликабельная ссылка `tc-pass-link` в карточке записи
  (`schedule-editor-main.js`) + CSS в `mini-app-components.css` (перенесено из
  `wip/schedule-editor-010-042`).
- 2026-09-04 | верификация: 3/3 unit-теста зелёные (AC-001/AC-002), браузерная проверка
  на throwaway тренере подтвердила AC-003 (ссылка «QA Пробный абонемент: 7 из 10»,
  корректный href). Тестовые данные удалены.
- 2026-09-04 | COMPLETE
