/**
 * TASK-109: hub slot back-stack + BYN price suffix (no NBRB PUA glyph).
 * Run: node --test tests/js/booking-client.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const bookingClientPath = path.resolve(__dirname, '../../static/webapp/booking-client.js');
const catalogMainPath = path.resolve(__dirname, '../../static/webapp/catalog-main.js');

function loadBookingClient() {
  const resolved = require.resolve(bookingClientPath);
  delete require.cache[resolved];
  return require(bookingClientPath).BookingClient;
}

describe('catalogFormBackAction (TASK-109 hub nearest slot)', () => {
  it('returns hub from booking form when opened via from=hub&slot_id (nearest-slot chip)', () => {
    const { catalogFormBackAction } = loadBookingClient();
    const qp = new URLSearchParams('trainer_id=12&slot_id=99&service_id=3&from=hub');
    assert.equal(catalogFormBackAction(qp, 'screenBookingForm'), 'hub');
  });

  it('keeps hub → action=book form back on slot pick, and slot pick back on hub', () => {
    const { catalogFormBackAction } = loadBookingClient();
    const qp = new URLSearchParams('trainer_id=12&action=book&from=hub');
    assert.equal(catalogFormBackAction(qp, 'screenBookingForm'), 'slot-pick');
    assert.equal(catalogFormBackAction(qp, 'screenSlotPick'), 'hub');
  });

  it('falls back to trainer card when catalog opened the form without hub origin', () => {
    const { catalogFormBackAction } = loadBookingClient();
    const qp = new URLSearchParams('trainer_id=12&slot_id=99');
    assert.equal(catalogFormBackAction(qp, 'screenBookingForm'), 'trainer-detail');
  });
});

describe('formatPriceAmountHtml (TASK-109 BYN, no tofu)', () => {
  it('appends BYN letters, never the NBRB private-use glyph', () => {
    const { formatPriceAmountHtml } = loadBookingClient();
    const html = formatPriceAmountHtml(50, 'BYN');
    assert.equal(html, '50 BYN');
    assert.doesNotMatch(html, /e901|nbrb-icon|\uE901/);
  });

  it('keeps руб. for RUB', () => {
    const { formatPriceAmountHtml } = loadBookingClient();
    assert.equal(formatPriceAmountHtml(55, 'RUB'), '55 руб.');
  });
});

describe('catalog-main.js wiring', () => {
  it('does not inject nbrb-icon / U+E901 into price-tier radios', () => {
    const src = fs.readFileSync(catalogMainPath, 'utf8');
    assert.doesNotMatch(src, /nbrb-icon/);
    assert.doesNotMatch(src, /e901/);
    // TASK-196: валюта тира — из полезной нагрузки (руб. для RUB), не «BYN» наизусть.
    assert.match(src, /priceNum \+ ' ' \+ priceCurrencyLabel\(tier\.currency_code\)/);
    assert.match(src, /get\('slot_id'\)/);
  });
});

describe('slotsUrl (TASK-357)', () => {
  it('init_data идёт отдельным параметром, а не хвостом service_id', () => {
    const { slotsUrl } = loadBookingClient();
    const url = slotsUrl({ trainer_id: 9, service_id: 1 }, 'a=1&hash=x');
    assert.equal((url.match(/\?/g) || []).length, 1, url);
    assert.equal(url, '/api/webapp/client/slots?trainer_id=9&service_id=1&init_data=a%3D1%26hash%3Dx');
  });

  it('слот-запрос несёт trainer_id, service_id и arena_id одним «?»', () => {
    const { slotsUrl } = loadBookingClient();
    const url = slotsUrl({ trainer_id: 7, service_id: 3, arena_id: 9 }, 'user=1');
    assert.equal((url.match(/\?/g) || []).length, 1, url);
    const u = new URL(url, 'https://x');
    assert.equal(u.pathname, '/api/webapp/client/slots');
    assert.equal(u.searchParams.get('trainer_id'), '7');
    assert.equal(u.searchParams.get('service_id'), '3');
    assert.equal(u.searchParams.get('arena_id'), '9');
    assert.equal(u.searchParams.get('init_data'), 'user=1');
  });

  it('без init_data вопрос один и параметры на месте', () => {
    const { slotsUrl } = loadBookingClient();
    assert.equal(slotsUrl({ trainer_id: 7, service_id: 3 }, ''), '/api/webapp/client/slots?trainer_id=7&service_id=3');
  });
});
