/**
 * TASK-397: коды нажатий карточки. Телефон и initData в событие не входят.
 * Run: node --test tests/js/booking-source-measure.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourceJs = fs.readFileSync(
  path.resolve(__dirname, '../../static/webapp/booking-source.js'),
  'utf8'
);

function load() {
  const win = { location: { search: '', pathname: '/webapp/trainers' }, URLSearchParams };
  win.window = win;
  vm.createContext(win);
  vm.runInContext(sourceJs, win);
  return win.GlideBookingSource;
}

describe('card measure codes', () => {
  const S = load();

  it('maps the card buttons', () => {
    assert.equal(S.ctaAction('slot', 'cta'), 'book');
    assert.equal(S.ctaAction('slot', ''), 'slot');
    assert.equal(S.ctaAction('win', ''), 'slot');
    assert.equal(S.ctaAction('write', ''), 'write');
    assert.equal(S.ctaAction('copy-phone', ''), 'call');
    assert.equal(S.ctaAction('request', ''), 'request');
    assert.equal(S.ctaAction('save', ''), null);
  });

  it('classifies the first tap after a trainer-link registration', () => {
    assert.equal(S.classifyFirstTap('trainer', ''), 'card');
    assert.equal(S.classifyFirstTap('slot', ''), 'slot');
    assert.equal(S.classifyFirstTap('', '/webapp/book?trainer_id=3'), 'slot');
    assert.equal(S.classifyFirstTap('', '/webapp/trainers?trainer_id=3'), 'card');
    assert.equal(S.classifyFirstTap('', '/webapp/client-home'), 'hub');
  });

  it('event bodies carry only the measure fields', () => {
    const bodies = [...sourceJs.matchAll(/postCardEvent\(ctx, (\{[^}]*\})\)/g)].map((m) => m[1]);
    assert.equal(bodies.length, 4);
    for (const body of bodies) {
      assert.equal(/initData|phone|first_name|name\s*:/.test(body), false);
      assert.match(body, /trainer_id/);
    }
  });
});
