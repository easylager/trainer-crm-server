/**
 * Вкладки блока «На льду» в карточке арены Mini App (как на сайте).
 * Run: node --test tests/js/arena-card-ice-tabs.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/webapp/arena-card-model.js'));

const four = [
  { key: 'skate', full: 'Массовое катание' },
  { key: 'family', full: 'Семейное массовое катание' },
  { key: 'figure', full: 'Свободное фигурное катание' },
  { key: 'ohm', full: 'ОХМ' },
];

describe('iceTabsView', () => {
  it('shows no tabs for fewer than two kinds', () => {
    assert.equal(M.iceTabsView([], null, '').show, false);
    const one = M.iceTabsView([four[0]], null, '');
    assert.equal(one.show, false);
    assert.equal(one.active, 'skate');
  });

  it('uses short labels from three tabs, full ones for two', () => {
    const v4 = M.iceTabsView(four, null, '');
    assert.deepEqual(v4.items.map((i) => i.label), ['Массовое', 'Семейное', 'Фигурное', 'ОХМ']);
    const v2 = M.iceTabsView([four[0], four[3]], null, '');
    assert.deepEqual(v2.items.map((i) => i.label), ['Массовое катание', 'ОХМ']);
  });

  it('active: current tab, else the kind of the linked session, else the first', () => {
    assert.equal(M.iceTabsView(four, 'figure', 'ohm').active, 'figure');
    assert.equal(M.iceTabsView(four, null, 'ohm').active, 'ohm');
    assert.equal(M.iceTabsView(four, null, '').active, 'skate');
    // вкладки, которой больше нет, не выбираем
    assert.equal(M.iceTabsView([four[1], four[3]], 'skate', 'figure').active, 'family');
  });
});
