/**
 * TASK-436: маячок просмотра передаёт bell=1, когда на странице показан колокольчик зимы.
 * Run: node --test tests/js/public-page-view-beacon.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const src = fs.readFileSync(path.resolve(__dirname, '../../static/shared/public-page-view-beacon.js'), 'utf8');

function run(attrs) {
  const sent = [];
  const script = { getAttribute: (k) => (k in attrs ? attrs[k] : null) };
  const ctx = {
    URLSearchParams,
    document: { currentScript: script, prerendering: false },
    location: { pathname: '/c/minsk/zimoy', search: '' },
    navigator: { sendBeacon: (u) => sent.push(u) },
  };
  ctx.globalThis = ctx;
  vm.runInNewContext(src, ctx);
  assert.equal(sent.length, 1);
  return new URL(sent[0], 'https://x').searchParams;
}

describe('public-page-view-beacon', () => {
  it('data-bell="1" едет как bell=1', () => {
    const q = run({ 'data-surface': 'selection_page', 'data-city-id': '2', 'data-bell': '1' });
    assert.equal(q.get('bell'), '1');
    assert.equal(q.get('path'), '/c/minsk/zimoy');
  });

  it('без колокольчика параметра нет', () => {
    const q = run({ 'data-surface': 'selection_page', 'data-city-id': '2' });
    assert.equal(q.get('bell'), null);
  });
});
