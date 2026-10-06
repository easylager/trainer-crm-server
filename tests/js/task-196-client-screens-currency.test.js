/**
 * TASK-196 (ревью-доработка): клиентские экраны рисуют цену тренера
 * в валюте его города (RU → ₽, BY → BYN), а не «BYN» наизусть.
 *
 * Четыре экрана: заявки (client-requests-main), сохранённые тренеры
 * (client-saved-trainers-main), запись (book.html), «Мои записи»
 * (client-bookings.html). Полезные нагрузки без валюты читаются как BYN —
 * условие совместимости со старым кэшем.
 *
 * Run: node --test tests/js/task-196-client-screens-currency.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEBAPP = path.resolve(__dirname, '../../static/webapp');

function src(name) {
  return fs.readFileSync(path.join(WEBAPP, name), 'utf8');
}

function sliceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  assert.ok(start >= 0, 'marker not found: ' + startMarker);
  const end = source.indexOf(endMarker, start);
  assert.ok(end > start, 'end marker not found: ' + endMarker);
  return source.slice(start, end + endMarker.length);
}

/** Экран заявок: услуги и цены отвечающих (/client/requests → currency_code на услуге). */
function loadRequestsFormatter() {
  const S = src('client-requests-main.js');
  const code =
    sliceBetween(S, 'function escapeHtml(s) {', '\n      }') +
    '\n' +
    sliceBetween(S, 'function priceCurrencyLabel(code) {', '\n      }') +
    '\n' +
    sliceBetween(S, 'function formatResponderServicePrice(s) {', '\n      }') +
    '\nmodule.exports = { formatResponderServicePrice: formatResponderServicePrice };';
  const ctx = { module: { exports: {} } };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.module.exports;
}

/** Экран сохранённых: чип «от X …» (/client/trainer-edges → currency_code на ребре). */
function loadSavedTrainersFormatter() {
  const S = src('client-saved-trainers-main.js');
  const code =
    sliceBetween(S, 'function esc(s) {', '\n  }') +
    '\n' +
    sliceBetween(S, 'function priceCurrencyLabel(code) {', '\n  }') +
    '\n' +
    sliceBetween(S, 'function priceByn(cents, currency) {', '\n  }') +
    '\nmodule.exports = { priceByn: priceByn };';
  const ctx = { module: { exports: {} } };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.module.exports;
}

/** Экран записи: цена услуги и тиры (/api/public/trainers/{id} → currency_code). */
function loadBookFormatters() {
  const S = src('book.html');
  const code =
    sliceBetween(S, 'function priceCurrencyLabel(code) {', '\n      }') +
    '\n' +
    sliceBetween(S, 'function formatBookServicePrice(s) {', '\n      }') +
    '\nmodule.exports = { formatBookServicePrice: formatBookServicePrice, priceCurrencyLabel: priceCurrencyLabel };';
  const ctx = { module: { exports: {} } };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.module.exports;
}

/** «Мои записи»: стоимость записи (/client/bookings → currency_code на записи). */
function loadBookingsFormatter() {
  const S = src('client-bookings.html');
  const code =
    sliceBetween(S, 'function priceCurrencyLabel(code) {', '\n      }') +
    '\n' +
    sliceBetween(S, 'function formatBynFromCents(cents, currency) {', '\n      }') +
    '\nmodule.exports = { formatBynFromCents: formatBynFromCents };';
  const ctx = { module: { exports: {} } };
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.module.exports;
}

describe('заявки: цена услуги отвечающего — в валюте его города', () => {
  it('тренер из RU-города → «от 40 ₽» и «40 ₽»', () => {
    const { formatResponderServicePrice } = loadRequestsFormatter();
    assert.equal(
      formatResponderServicePrice({ price_byn_min: 40, price_byn_max: 60, currency_code: 'RUB' }),
      'от 40 ₽'
    );
    assert.equal(formatResponderServicePrice({ price_byn: 40, currency_code: 'RUB' }), '40 ₽');
  });

  it('услуга без валюты читается как BYN', () => {
    const { formatResponderServicePrice } = loadRequestsFormatter();
    assert.equal(formatResponderServicePrice({ price_byn: 25 }), '25 BYN');
  });
});

describe('сохранённые тренеры: чип «от X …» — в валюте тренера', () => {
  it('тренер из RU-города → «от 4000 ₽»', () => {
    const { priceByn } = loadSavedTrainersFormatter();
    assert.equal(priceByn(400000, 'RUB'), 'от 4000 ₽');
  });

  it('ребро без валюты читается как BYN', () => {
    const { priceByn } = loadSavedTrainersFormatter();
    assert.equal(priceByn(150000), 'от 1500 BYN');
    assert.equal(priceByn(150000, undefined), 'от 1500 BYN');
  });
});

describe('экран записи: цена услуги и тир — в валюте тренера', () => {
  it('тренер из RU-города → «от 40 ₽» / «40 ₽»', () => {
    const { formatBookServicePrice, priceCurrencyLabel } = loadBookFormatters();
    assert.equal(
      formatBookServicePrice({ price_byn_min: 40, price_byn_max: 60, currency_code: 'RUB' }),
      'от 40 ₽'
    );
    assert.equal(formatBookServicePrice({ price_byn: 40, currency_code: 'RUB' }), '40 ₽');
    assert.equal(priceCurrencyLabel('RUB'), '₽');
  });

  it('услуга без валюты читается как BYN', () => {
    const { formatBookServicePrice } = loadBookFormatters();
    assert.equal(formatBookServicePrice({ price_byn: 25 }), '25 BYN');
  });
});

describe('«Мои записи»: стоимость записи — в валюте её тренера', () => {
  it('запись к тренеру из RU-города → «4000 ₽»', () => {
    const { formatBynFromCents } = loadBookingsFormatter();
    assert.equal(formatBynFromCents(400000, 'RUB'), '4000 ₽');
    assert.equal(formatBynFromCents(125000, 'RUB'), '1250 ₽');
  });

  it('запись без валюты читается как BYN', () => {
    const { formatBynFromCents } = loadBookingsFormatter();
    assert.equal(formatBynFromCents(150000), '1500 BYN');
  });
});
