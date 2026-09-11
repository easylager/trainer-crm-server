/**
 * Ice map layout: fill viewport; mini card above «Список», not under it.
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

describe('ice map layout (карта + мини-карточка)', () => {
  it('в режиме карты растягивает сцену и не поднимает пилюлю в центр', () => {
    const css = read('ice-tab.css');
    assert.match(css, /body\.ice-view-map\s+\.ice-map-stage/);
    assert.match(css, /body\.ice-view-map\s+\.ice-map-sheet/);
    assert.ok(!/ice-map-sheet-open/.test(css), 'старый сдвиг пилюли в центр убран');
  });

  it('мини-карточка absolute над пилюлей, пилюля остаётся у таб-бара', () => {
    const css = read('ice-tab.css');
    const sheet = css.slice(css.indexOf('body.ice-view-map .ice-map-sheet'), css.indexOf('body.ice-view-map .ice-map-sheet:empty'));
    assert.match(sheet, /position:\s*absolute/);
    assert.match(sheet, /bottom:\s*58px/);
    assert.ok(!/ice-map-sheet-open[\s\S]{0,80}104px/.test(css));
  });

  it('тело помечается ice-view-map при включении карты', () => {
    const js = read('ice-tab.js');
    assert.match(js, /ice-view-map/);
    assert.ok(!/scrollIntoView/.test(js) || !/mapSec\.scrollIntoView/.test(js));
  });
});
