/**
 * Ice map: «Список» FAB must clear the selected-arena mini card.
 * Run: node --test tests/js/ice-map-sheet-fab.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

describe('ice map sheet vs Список FAB', () => {
  it('поднимает пилюлю, когда открыта мини-карточка', () => {
    const css = read('ice-tab.css');
    assert.match(css, /body\.ice-map-sheet-open\s+\.ice-viewswitch/);
    assert.match(css, /104px/);
  });

  it('ставит класс на body при отрисовке sheet', () => {
    const js = read('ice-map.js');
    assert.match(js, /syncSheetFabClearance/);
    assert.match(js, /ice-map-sheet-open/);
  });
});
