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

  it('keeps ₽ for RUB', () => {
    const { formatPriceAmountHtml } = loadBookingClient();
    assert.equal(formatPriceAmountHtml(55, 'RUB'), '55 ₽');
  });
});

describe('catalog-main.js wiring', () => {
  it('does not inject nbrb-icon / U+E901 into price-tier radios', () => {
    const src = fs.readFileSync(catalogMainPath, 'utf8');
    assert.doesNotMatch(src, /nbrb-icon/);
    assert.doesNotMatch(src, /e901/);
    assert.match(src, /priceNum \+ ' BYN'/);
    assert.match(src, /get\('slot_id'\)/);
  });
});
