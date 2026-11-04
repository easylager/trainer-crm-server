/**
 * Шторка «Что ищем»: тап по текущей категории выводит из зимних точек.
 * Run: node --test tests/js/ice-tab-intent-leaves-winter.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/webapp/ice-tab-model.js'));

describe('intentPickShouldApply', () => {
  it('applies a category that is not current', () => {
    assert.equal(M.intentPickShouldApply(false, ''), true);
    assert.equal(M.intentPickShouldApply(false, 'winter'), true);
  });

  it('ignores a tap on the current category — unless winter is on', () => {
    assert.equal(M.intentPickShouldApply(true, ''), false);
    assert.equal(M.intentPickShouldApply(true, 'winter'), true);
  });
});

describe('syncWinter keeps both list hosts', () => {
  it('clears only the active list, never the #iceList wrapper', () => {
    const fs = require('node:fs');
    const src = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/ice-tab.js'), 'utf8');
    const body = src.slice(src.indexOf('function syncWinter()'), src.indexOf('function commitPlaceFilter('));
    assert.match(body, /var list = listEl\(\);/);
    assert.doesNotMatch(body, /\$\('iceList'\)/);
  });
});
