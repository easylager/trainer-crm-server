/**
 * TASK-096 AC-004 — момент первого успеха на экране записи.
 *
 * Гейт, а не разовая проверка: экран первого успеха легче всего «улучшить» выдуманной
 * бодростью — обещанием напоминаний, которых не будет, или срочностью, которой нет.
 * Здесь эта граница закреплена тестом.
 *
 * Run: node --test tests/js/booking-first-success.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modulePath = path.resolve(__dirname, '../../static/webapp/booking-client.js');

function load() {
  const resolved = require.resolve(modulePath);
  delete require.cache[resolved];
  const m = require(modulePath);
  return m.BookingClient || m;
}

describe('formatSuccessMessage: первая запись против последующих', () => {
  it('обычная запись оставляет прежний экран без изменений', () => {
    const { formatSuccessMessage } = load();
    const html = formatSuccessMessage({ success: true, booking_id: 7 }, {});
    assert.match(html, /Вы записаны/);
    assert.ok(!html.includes('booking-first-success'));
    // Прежний экран продолжает говорить, где искать детали.
    assert.match(html, /Мои записи/);
  });

  it('первая запись подтверждает успех и называет следующий шаг', () => {
    const { formatSuccessMessage } = load();
    const html = formatSuccessMessage(
      { success: true, is_first_booking: true, reminder_plan: 'за сутки и за два часа до начала' },
      {}
    );
    assert.match(html, /первая запись/i);
    assert.match(html, /booking-first-success__steps/);
    // Следующий шаг назван, и он настоящий: подтверждение приходит в бот.
    assert.match(html, /Тренер подтвердит/);
    assert.match(html, /Моих записях/);
  });

  it('план напоминаний берётся из данных, а не сочиняется на клиенте', () => {
    const { formatSuccessMessage } = load();
    const withPlan = formatSuccessMessage(
      { is_first_booking: true, reminder_plan: 'накануне вечером до начала' },
      {}
    );
    assert.match(withPlan, /накануне вечером до начала/);
    // Клиент не подставляет «за 24 часа» по умолчанию.
    assert.ok(!withPlan.includes('за сутки'));
  });

  it('без плана напоминаний строки про напоминания нет вовсе', () => {
    const { formatSuccessMessage } = load();
    const html = formatSuccessMessage({ is_first_booking: true }, {});
    assert.match(html, /первая запись/i);
    assert.ok(!/[Нн]апомним/.test(html), 'обещание напоминания без плана — выдуманные данные');
    // Экран всё равно остаётся полезным: два честных шага вместо трёх.
    assert.match(html, /Тренер подтвердит/);
    assert.match(html, /Моих записях/);
  });

  it('не дублирует строку про «Мои записи» дважды на одном экране', () => {
    const { formatSuccessMessage } = load();
    const html = formatSuccessMessage({ is_first_booking: true }, {});
    const hits = html.match(/Мои[хм]? запис/g) || [];
    assert.equal(hits.length, 1);
  });

  it('контекст заявки сохраняется и на экране первого успеха', () => {
    const { formatSuccessMessage } = load();
    const html = formatSuccessMessage({ is_first_booking: true }, { requestId: 42 });
    assert.match(html, /первая запись/i);
    assert.match(html, /связана с вашей заявкой/);
  });

  it('никакой выдуманной срочности и фальшивого социального сигнала (AC-005)', () => {
    const { formatSuccessMessage } = load();
    const html = formatSuccessMessage(
      { is_first_booking: true, reminder_plan: 'за сутки и за два часа до начала' },
      {}
    );
    for (const forbidden of ['осталось', 'смотрят', 'успей', 'только сегодня', 'мест ']) {
      assert.ok(!html.toLowerCase().includes(forbidden), 'запрещённая формулировка: ' + forbidden);
    }
    // Ни рейтингов, ни счётчиков «уже записались N человек».
    assert.ok(!/\b\d+\s+(человек|людей)\b/.test(html));
  });

  it('план напоминаний экранируется, а не вставляется как разметка', () => {
    const { formatSuccessMessage } = load();
    const html = formatSuccessMessage(
      { is_first_booking: true, reminder_plan: '<img src=x onerror=alert(1)>' },
      {}
    );
    assert.ok(!html.includes('<img'));
    assert.match(html, /&lt;img/);
  });
});
